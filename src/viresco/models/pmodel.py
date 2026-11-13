"""
Viresco-compatible interface to PyRealm's 'P-model'.

This module provides the pmodel node, which wraps the pyrealm P-Model and returns
every output pyrealm declares: gross primary productivity (GPP), light use efficiency
(LUE), intrinsic water use efficiency (IWUE), Vcmax and Jmax at growth and standard
temperature, and stomatal conductance.

Some of pyrealm's methods need inputs beyond the core drivers. Each method axis
that has any such method gets an ``<axis>_inputs`` node, defined once per set of
requirements and selected by ``@config.when`` on the configured method, so a
pipeline only asks for what its chosen methods consume. Each variant returns the
extra inputs keyed by their pyrealm ``PModelEnvironment`` argument names, and
`pmodel` passes the union through.
"""

from collections.abc import Mapping
from typing import Annotated, Any, TypedDict, cast

import pyrealm.pmodel
import xarray as xr
from catena.io import sole_time_dim
from hamilton.function_modifiers import config, extract_fields
from numpy.typing import NDArray
from pyrealm.pmodel.arrhenius import ARRHENIUS_METHOD_REGISTRY
from pyrealm.pmodel.optimal_chi import OPTIMAL_CHI_CLASS_REGISTRY
from pyrealm.pmodel.quantum_yield import QUANTUM_YIELD_CLASS_REGISTRY
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from ..temporal import DAILY


class PModelOut(TypedDict):
    """Outputs of the `pmodel` node, at daily resolution."""

    gpp_flux: Annotated[DataArray, Unit("ug m-2 s-1"), DAILY]
    """Carbon fixed by photosynthesis, as the flux pyrealm reports (micrograms of
    carbon per square metre per second), averaged over the day as the drivers are.

    Not a daily total. A consumer wanting ``g m-2 d-1`` multiplies by 0.0864
    (86400 s d-1 x 1e-6 g ug-1). The example config does that in its
    ``gpp_weekly`` node, after a weekly mean."""
    lue_photon: Annotated[DataArray, Unit("g mol-1"), DAILY]
    """Light use efficiency, as carbon fixed per *mole of absorbed photons*
    (grams of carbon per mole).

    pyrealm defines LUE against PPFD, a photon flux, so the denominator counts
    photons rather than energy. SGAM wants ``g MJ-1`` instead, and the two differ
    by the energy content of PAR, roughly 4.57 mol MJ-1."""
    iwue: Annotated[DataArray, Unit("umol mol-1"), DAILY]
    """Intrinsic water use efficiency (micromoles of CO2 per mole of air).

    pyrealm computes ``(5/8)(ca - ci) / P`` with the partial pressures in Pa and
    ``P`` in megapascals, so this is a mixing ratio rather than a pressure."""
    vcmax: Annotated[DataArray, Unit("umol m-2 s-1"), DAILY]
    """Maximum rate of carboxylation at the growth temperature."""
    vcmax25: Annotated[DataArray, Unit("umol m-2 s-1"), DAILY]
    """Maximum rate of carboxylation at 25 degC, scaled from Vcmax by
    ``method_arrhenius``."""
    jmax: Annotated[DataArray, Unit("umol m-2 s-1"), DAILY]
    """Maximum rate of electron transport at the growth temperature."""
    jmax25: Annotated[DataArray, Unit("umol m-2 s-1"), DAILY]
    """Maximum rate of electron transport at 25 degC, scaled from Jmax by
    ``method_arrhenius``."""
    gs: Annotated[DataArray, Unit("umol m-2 s-1"), DAILY]
    """Stomatal conductance, NaN where VPD is 0 or ``ca - ci`` is not positive.

    The units are the ones pyrealm declares. pyrealm computes this as
    ``A_c / (ca - ci)`` with the partial pressures in Pa, which is dimensionally
    also per pascal."""


#: `PModelOut` field -> the `pyrealm.pmodel.PModel` attribute holding it.
_OUTPUT_ATTRIBUTES = {
    "gpp_flux": "gpp",
    "lue_photon": "lue",
    "iwue": "iwue",
    "vcmax": "vcmax",
    "vcmax25": "vcmax25",
    "jmax": "jmax",
    "jmax25": "jmax25",
    "gs": "gs",
}


def _pmodel_block(
    temperature: NDArray,
    vpd: NDArray,
    co2: NDArray,
    pressure: NDArray,
    fapar: NDArray,
    ppfd: NDArray,
    *extra_values: NDArray,
    extra_names: tuple[str, ...],
    method_optchi: str,
    method_jmaxlim: str,
    method_kphio: str,
    method_arrhenius: str,
    reference_kphio: float | None = None,
) -> tuple[NDArray, ...]:
    """Run the P-Model on a whole numpy block (element-wise over every cell).

    pyrealm's P-Model is vectorised over the spatial axis, so this kernel runs on the
    full array — or a single dask chunk — in one call; there is no per-pixel loop.
    ``extra_values`` are the method-dependent inputs, passed positionally because
    `xarray.apply_ufunc` only maps over positional arguments, and named by
    ``extra_names`` in the same order.
    Returns one array per entry of `_OUTPUT_ATTRIBUTES`, in that order, matching the
    input shape, in pyrealm's own units. Nothing is rescaled here. This is the unit
    mapped over the block by `_pmodel` via `xarray.apply_ufunc`.
    """
    # Typed `Any` because pyrealm takes these through `**kwargs`, alongside
    # keyword arguments of other types that a `dict[str, NDArray]` would clash with.
    extras: dict[str, Any] = dict(zip(extra_names, extra_values, strict=True))
    # Environmental drivers computed upon instantiation of PModelEnvironment
    env = pyrealm.pmodel.PModelEnvironment(
        tc=temperature,
        vpd=vpd,
        co2=co2,
        patm=pressure,
        fapar=fapar,
        ppfd=ppfd,
        **extras,
    )
    # P-model fit performed upon instantiation of Pmodel
    model = pyrealm.pmodel.PModel(
        env=env,
        method_optchi=method_optchi,
        method_kphio=method_kphio,
        method_arrhenius=method_arrhenius,
        method_jmaxlim=method_jmaxlim,
        reference_kphio=reference_kphio,
    )

    return tuple(getattr(model, name) for name in _OUTPUT_ATTRIBUTES.values())


def _pmodel(
    temperature: DataArray,
    vpd: DataArray,
    co2: DataArray,
    pressure: DataArray,
    fapar: DataArray,
    ppfd: DataArray,
    extra_inputs: dict[str, DataArray],
    method_optchi: str,
    method_jmaxlim: str,
    method_kphio: str,
    method_arrhenius: str,
    reference_kphio: float | None = None,
) -> PModelOut:
    """Apply the P-Model to a ``(time, space)`` block via `xarray.apply_ufunc`.

    The P-Model is element-wise (every cell independent), so no core dimensions are
    declared and ``apply_ufunc`` broadcasts over every dimension, whatever its name;
    pyrealm still vectorises within each call. ``dask="parallelized"`` is a no-op
    for eager numpy inputs but keeps the node compatible with a future dask-backed
    (chunked) execution strategy.

    ``extra_inputs`` holds the method-dependent inputs, keyed by pyrealm's
    ``PModelEnvironment`` argument names, as the ``<axis>_inputs`` nodes return
    them.
    """
    # Some extra inputs (`mean_growth_temperature`, `aridity_index`) are
    # climatological: one value per pixel, no time axis. apply_ufunc would hand
    # them to the kernel with a length-1 time axis, and pyrealm's
    # `check_input_shapes` rejects that rather than broadcasting it, so expand them
    # here. Broadcasting an input that already has a time axis is a no-op.
    extra_names = tuple(extra_inputs)
    extra_values = [
        extra_inputs[name].broadcast_like(temperature) for name in extra_names
    ]

    n_outputs = len(_OUTPUT_ATTRIBUTES)
    outputs = xr.apply_ufunc(
        _pmodel_block,
        temperature,
        vpd,
        co2,
        pressure,
        fapar,
        ppfd,
        *extra_values,
        kwargs={
            "extra_names": extra_names,
            "method_optchi": method_optchi,
            "method_jmaxlim": method_jmaxlim,
            "method_kphio": method_kphio,
            "method_arrhenius": method_arrhenius,
            "reference_kphio": reference_kphio,
        },
        output_core_dims=[[]] * n_outputs,
        dask="parallelized",
        keep_attrs=False,
        output_dtypes=[float] * n_outputs,
    )
    return cast(
        PModelOut,
        dict(zip(_OUTPUT_ATTRIBUTES, outputs, strict=True)),
    )


@extract_fields()
@check_annotations
@stamp_output_units
def pmodel(
    temperature: Annotated[DataArray, Unit("degC"), DAILY],
    vpd: Annotated[DataArray, Unit("Pa"), DAILY],
    co2: Annotated[DataArray, Unit("ppm"), DAILY],
    pressure: Annotated[DataArray, Unit("Pa"), DAILY],
    fapar: Annotated[DataArray, Unit("1"), DAILY],
    ppfd: Annotated[DataArray, Unit("umol m-2 s-1"), DAILY],
    optchi_inputs: dict[str, DataArray],
    kphio_inputs: dict[str, DataArray],
    arrhenius_inputs: dict[str, DataArray],
    *,
    method_optchi: str = "prentice14",
    method_jmaxlim: str = "wang17",
    method_kphio: str = "temperature",
    method_arrhenius: str = "simple",
    reference_kphio: float | None = None,
) -> PModelOut:
    """Run the P-Model, returning every output pyrealm declares.

    Each method setting selects one of pyrealm's alternative formulations; the
    accepted values are pyrealm's, and the
    [pyrealm P-model documentation](https://pyrealm.readthedocs.io/en/latest/users/pmodel/module_overview.html)
    is the authoritative list. pyrealm's own warnings reach you unfiltered: it
    warns that some of these methods are experimental, and recommends ``simple``
    over the other ``method_arrhenius`` choices.

    Parameters
    ----------
    temperature
        Air temperature (degrees Celsius).
    vpd
        Vapour pressure deficit (pascals).
    co2
        Atmospheric CO2 concentration (parts per million).
    pressure
        Atmospheric pressure (pascals).
    fapar
        Fraction of absorbed photosynthetically active radiation
        (dimensionless, 0-1).
    ppfd
        Photosynthetic photon flux density (micromoles per square metre per
        second), as the mean rate over the 24-hour day, not a daily total. See
        `viresco.nodes.radiation` for deriving it from shortwave radiation or
        from SPLASH.
    optchi_inputs
        Extra inputs for the configured ``method_optchi``.
    kphio_inputs
        Extra inputs for the configured ``method_kphio``.
    arrhenius_inputs
        Extra inputs for the configured ``method_arrhenius``.

    Other Parameters
    ----------------
    method_optchi
        Formulation for optimal chi, the ratio of leaf-internal to ambient CO2:
        ``prentice14``, ``prentice14_rootzonestress``, ``c4``,
        ``c4_rootzonestress``, ``c4_no_gamma``, ``c4_no_gamma_rootzonestress``,
        ``lavergne20_c3`` or ``lavergne20_c4``. The ``lavergne20`` methods need
        soil moisture and the ``rootzonestress`` methods a root zone stress
        factor; see `optchi_inputs__theta` and `optchi_inputs__rootzonestress`.
    method_jmaxlim
        Jmax limitation: ``wang17``, ``smith19`` or ``none``.
    method_kphio
        Temperature dependence of the quantum yield efficiency (phi0):
        ``temperature``, ``fixed`` or ``sandoval``. ``sandoval`` needs
        climatological inputs; see `kphio_inputs__sandoval`.
    method_arrhenius
        Arrhenius temperature scaling of ``vcmax25`` and ``jmax25``,
        the only outputs it affects: ``simple`` or ``kattge_knorr``.
        ``kattge_knorr`` needs the mean growth temperature; see
        `arrhenius_inputs__kattge_knorr`.
    reference_kphio
        Reference value of the quantum yield efficiency, as one number for the
        whole run. Unset, ``method_kphio`` uses pyrealm's default for that method.

    Returns
    -------
    PModelOut
        Dictionary of daily outputs:

        - gpp_flux: gross primary productivity (micrograms of carbon per
          square metre per second)
        - lue_photon: light use efficiency (grams of carbon per mole of
          absorbed photons)
        - iwue: intrinsic water use efficiency (micromoles per mole)
        - vcmax, vcmax25: maximum carboxylation rate at the growth
          temperature and at 25 degC (micromoles per square metre per second)
        - jmax, jmax25: maximum electron transport rate at the growth
          temperature and at 25 degC (micromoles per square metre per second)
        - gs: stomatal conductance

        See `PModelOut` for per-output detail.
    """
    # Two axes can ask for the same input (`mean_growth_temperature`), and then
    # both entries are the same node's value, so the merge loses nothing.
    return _pmodel(
        temperature=temperature,
        vpd=vpd,
        co2=co2,
        pressure=pressure,
        fapar=fapar,
        ppfd=ppfd,
        extra_inputs={**optchi_inputs, **kphio_inputs, **arrhenius_inputs},
        method_optchi=method_optchi,
        method_jmaxlim=method_jmaxlim,
        method_kphio=method_kphio,
        method_arrhenius=method_arrhenius,
        reference_kphio=reference_kphio,
    )


def _methods_requiring(
    registry: Mapping[str, type], attribute: str, *requirements: str
) -> tuple[str, ...]:
    """Select the methods in a pyrealm registry declaring exactly these requirements."""
    # No getattr default: if pyrealm renames the attribute, fail on import rather
    # than read every method as needing nothing.
    return tuple(
        method
        for method, cls in registry.items()
        if getattr(cls, attribute) == list(requirements)
    )


# Methods that need inputs beyond the core drivers, grouped by what they need, as
# pyrealm declares it. A method in none of these gets the empty
# `<axis>_inputs__none` variant, and so does an unset key: the config's defaults live
# on `pmodel`, which `config.when` cannot see, so this only holds while every
# default method needs nothing extra. `tests/test_pmodel_methods.py` checks that
# invariant, and fails on a requirement set that has no variant here.
#
# The `<axis>_inputs` nodes re-hash and re-store their arrays under a result cache,
# and must: `@cache(behavior="ignore")` would drop them from `pmodel`'s cache key and
# serve stale results, and `"disable"` would make `pmodel` miss on every run.
_OPTCHI_THETA = _methods_requiring(OPTIMAL_CHI_CLASS_REGISTRY, "requires", "theta")
_OPTCHI_ROOTZONESTRESS = _methods_requiring(
    OPTIMAL_CHI_CLASS_REGISTRY, "requires", "rootzonestress"
)
_KPHIO_SANDOVAL = _methods_requiring(
    QUANTUM_YIELD_CLASS_REGISTRY,
    "requires",
    "aridity_index",
    "mean_growth_temperature",
)
_ARRHENIUS_KATTGE_KNORR = _methods_requiring(
    ARRHENIUS_METHOD_REGISTRY, "required_env_variables", "mean_growth_temperature"
)


@config.when_not_in(method_optchi=[*_OPTCHI_THETA, *_OPTCHI_ROOTZONESTRESS])
def optchi_inputs__none() -> dict[str, DataArray]:
    """No extra inputs, for the ``method_optchi`` choices that need none."""
    return {}


@config.when_in(method_optchi=list(_OPTCHI_THETA))
@check_annotations
def optchi_inputs__theta(
    volumetric_water_content: Annotated[DataArray, Unit("m3 m-3"), DAILY],
) -> dict[str, DataArray]:
    """Soil moisture, for ``method_optchi = "lavergne20_c3"`` or ``"lavergne20_c4"``.

    Parameters
    ----------
    volumetric_water_content
        Volumetric soil water content: the fraction of soil volume occupied by
        water (cubic metres of water per cubic metre of soil). This is pyrealm's
        ``theta``, not SPLASH's soil moisture, which is a depth of water in
        millimetres — see the ``volumetric_water_content`` node in the example
        config for the conversion.
    """
    return {"theta": volumetric_water_content}


@config.when_in(method_optchi=list(_OPTCHI_ROOTZONESTRESS))
@check_annotations
def optchi_inputs__rootzonestress(
    rootzonestress: Annotated[DataArray, Unit("1"), DAILY],
) -> dict[str, DataArray]:
    """Root zone stress, for the ``*_rootzonestress`` ``method_optchi`` choices.

    Parameters
    ----------
    rootzonestress
        Root zone stress factor (dimensionless, 0-1), which penalises the
        cost ratio in the optimal chi calculation. Experimental in pyrealm.
    """
    return {"rootzonestress": rootzonestress}


@config.when_not_in(method_kphio=list(_KPHIO_SANDOVAL))
def kphio_inputs__none() -> dict[str, DataArray]:
    """No extra inputs, for the ``method_kphio`` choices that need none."""
    return {}


@config.when_in(method_kphio=list(_KPHIO_SANDOVAL))
@check_annotations
def kphio_inputs__sandoval(
    aridity_index: Annotated[DataArray, Unit("1")],
    mean_growth_temperature: Annotated[DataArray, Unit("degC")],
) -> dict[str, DataArray]:
    """Climatological inputs, for ``method_kphio = "sandoval"``.

    Parameters
    ----------
    aridity_index
        Climatological aridity index, PET/P: potential evapotranspiration over
        precipitation, both accumulated over the record. Values above 1 mean
        demand exceeds supply. Note the orientation — pyrealm wants PET/P, so a
        *higher* value is a *drier* site.
    mean_growth_temperature
        Mean growth temperature (degrees Celsius); see
        `mean_growth_temperature`.
    """
    return {
        "aridity_index": aridity_index,
        "mean_growth_temperature": mean_growth_temperature,
    }


@config.when_not_in(method_arrhenius=list(_ARRHENIUS_KATTGE_KNORR))
def arrhenius_inputs__none() -> dict[str, DataArray]:
    """No extra inputs, for the ``method_arrhenius`` choices that need none."""
    return {}


@config.when_in(method_arrhenius=list(_ARRHENIUS_KATTGE_KNORR))
@check_annotations
def arrhenius_inputs__kattge_knorr(
    mean_growth_temperature: Annotated[DataArray, Unit("degC")],
) -> dict[str, DataArray]:
    """Mean growth temperature, for ``method_arrhenius = "kattge_knorr"``.

    Parameters
    ----------
    mean_growth_temperature
        Mean growth temperature (degrees Celsius); see
        `mean_growth_temperature`.
    """
    return {"mean_growth_temperature": mean_growth_temperature}


@config(
    lambda cfg: (
        cfg.get("method_kphio") in _KPHIO_SANDOVAL
        or cfg.get("method_arrhenius") in _ARRHENIUS_KATTGE_KNORR
    ),
    config_used=["method_kphio", "method_arrhenius"],
)
@check_annotations
def mean_growth_temperature(
    temperature: Annotated[DataArray, Unit("degC"), DAILY],
) -> Annotated[DataArray, Unit("degC")]:
    """Mean temperature over the growing days of the record, one value per pixel.

    pyrealm consumes this as an *acclimation* quantity: the ``sandoval`` quantum
    yield method uses it to set the temperature at which the highest kphio is
    attained, and the ``kattge_knorr`` Arrhenius method to set the activation
    entropy of its temperature scaling. The instantaneous temperature response is a
    separate term, driven by ``tc``.

    The mean is taken over the whole record, not a rolling window, and over days
    above 0 degC only. A pixel that never rises above 0 degC over the record
    yields NaN. Under ``sandoval`` that propagates through kphio into GPP; under
    ``kattge_knorr`` it reaches only ``vcmax25`` and ``jmax25``.

    The node exists only when the configured ``method_kphio`` or
    ``method_arrhenius`` consumes it.

    Parameters
    ----------
    temperature
        Daily mean air temperature (degrees Celsius).
    """
    # Reduce over the whole record, not per week: a winter week with no day above
    # 0 degC is an ordinary week, and windowing turned it into a NaN in GPP.
    growing_days = temperature.where(temperature > 0.0)
    return growing_days.mean(sole_time_dim(temperature, "temperature"))
