"""Nodes that belong to no one model.

Each model module runs at a single frequency (see `viresco.temporal`). A node
that a model needs but that does not run at that model's frequency lives here
instead: `mean_growth_temperature` reduces a daily series to one value per
pixel for the P-model, and `disturbances` detects disturbance events in
daily observations for SGAM, which a config then resamples to weekly.

viresco registers this module under catena's ``catena.modules`` entry-point
group like the models, so a config enables it with a ``[shared]`` section, which
also holds its settings.
"""

from typing import Annotated

import numpy as np
import xarray as xr
from catena.io import sole_time_dim
from hamilton.function_modifiers import config
from numpy.typing import NDArray
from sgam import Disturbances
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from .._dims import space_dim
from ..temporal import DAILY
from .pmodel import _ARRHENIUS_KATTGE_KNORR, _KPHIO_SANDOVAL


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
    ``method_arrhenius`` of `viresco.models.pmodel` consumes it.

    Parameters
    ----------
    temperature
        Daily mean air temperature (degrees Celsius).
    """
    # Reduce over the whole record, not per week: a winter week with no day above
    # 0 degC is an ordinary week, and windowing turned it into a NaN in GPP.
    growing_days = temperature.where(temperature > 0.0)
    return growing_days.mean(sole_time_dim(temperature, "temperature"))


def _disturbances_block(
    temperature: NDArray[np.float64],
    gpp: NDArray[np.float64],
    lai: NDArray[np.float64],
    disturbance_threshold: NDArray[np.float64],
    *,
    growing_season_limit: float,
) -> NDArray[np.float64]:
    """Run disturbance detection on a whole pixel-block (vectorised over pixels).

    ``apply_ufunc`` places the ``time`` core dim last, so each time series arrives
    as ``(pixel, time)`` (or ``(time,)`` with no pixel broadcast) and the per-pixel
    ``disturbance_threshold`` as ``(pixel,)`` (or a 0-d scalar).
    `Disturbances.forward` diffs GPP/LAI along axis 0, so ``time`` is moved to
    the front for the call and the result moved back to ``(pixel, time)``.
    ``moveaxis`` is a no-op on a 1D ``(time,)`` array, so the single-pixel case is
    handled too.

    With ``time`` leading, the time series are ``(time, pixel)`` and the threshold
    ``(pixel,)`` broadcasts against them along the trailing axis, so the whole
    block is still one call: `Disturbances.forward` only ever uses
    ``disturbance_threshold`` in an elementwise numpy comparison, so an array of
    per-pixel thresholds works exactly like a scalar and no ``vectorize=True``
    map over pixels is needed.
    """
    temp = np.moveaxis(np.asarray(temperature, dtype=float), -1, 0)
    g = np.moveaxis(np.asarray(gpp, dtype=float), -1, 0)
    la = np.moveaxis(np.asarray(lai, dtype=float), -1, 0)
    detector = Disturbances(
        growing_season_limit=growing_season_limit,
        # Per-pixel array rather than the declared scalar; see the docstring.
        disturbance_threshold=np.asarray(disturbance_threshold, dtype=float),  # type: ignore[reportArgumentType]
    )
    result = detector.forward(temp, g, la, aggregate=False)
    return np.moveaxis(result, 0, -1)


def _disturbances(
    temperature: xr.DataArray,
    gpp_obs: xr.DataArray,
    lai_obs: xr.DataArray,
    disturbance_threshold: xr.DataArray,
    growing_season_limit: float,
) -> xr.DataArray:
    """Apply disturbance detection over the ``(time, space)`` block via apply_ufunc.

    Disturbance detection diffs along time (so time is the input/output core dim)
    but is otherwise element-wise over space (the broadcast/mapped dim); see
    `viresco._dims` for how each is found. ``disturbance_threshold`` is a per-pixel
    input with no core dim, so it broadcasts alongside the time series.
    ``vectorize`` is left ``False`` so the whole block reaches the numpy kernel in
    one call; ``dask="parallelized"`` keeps a future dask-backed (chunked over
    space) run reachable.
    """
    time = sole_time_dim(temperature, "temperature")
    space = space_dim(
        temperature=temperature,
        gpp_obs=gpp_obs,
        lai_obs=lai_obs,
        disturbance_threshold=disturbance_threshold,
    )
    out = xr.apply_ufunc(
        _disturbances_block,
        temperature,
        gpp_obs,
        lai_obs,
        disturbance_threshold,
        input_core_dims=[[time]] * 3 + [[]],
        output_core_dims=[[time]],
        kwargs={"growing_season_limit": growing_season_limit},
        dask="parallelized",
        keep_attrs=False,
        output_dtypes=[float],
    )

    # apply_ufunc drops the time coord (a core dim) and orders the output as
    # (space, time); reattach the coord and restore the canonical (time, space).
    return out.assign_coords({time: temperature.coords[time]}).transpose(time, space)


@check_annotations
@stamp_output_units
def disturbances(
    temperature: Annotated[xr.DataArray, Unit("degC"), DAILY],
    gpp_obs: Annotated[xr.DataArray, Unit("g m-2 d-1"), DAILY],
    lai_obs: Annotated[xr.DataArray, Unit("1"), DAILY],
    pft_params: xr.Dataset,
    *,
    growing_season_limit: float = 10.0,
) -> Annotated[xr.DataArray, Unit("1"), DAILY]:
    """Detect daily disturbance events from anomalous declines in GPP and LAI.

    A disturbance is flagged on a day that is (a) within the growing season, i.e.
    warmer than ``growing_season_limit``, and (b) shows a relative decline in
    *both* GPP and LAI larger than the PFT's ``disturbance_threshold``. The
    threshold is taken per pixel from the ``pft_params`` node, so crops (0.1)
    register far more events than trees (0.3), with shrubs (0.25) and grass
    (0.2) in between.

    SGAM consumes this as a weekly maximum, which a config makes with a
    ``[[resample]]`` entry using ``aggfunc = "max"``.

    Parameters
    ----------
    temperature
        Daily mean air temperature (degrees Celsius).
    gpp_obs
        Observed daily gross primary productivity (grams of carbon per square
        metre per day). Named apart from the P-model's modelled GPP, which is
        weekly, so the two do not read as one variable at two frequencies.
    lai_obs
        Observed daily leaf area index (dimensionless).
    pft_params
        PFT parameters for each pixel. Output of the
        `viresco.models.sgam.pft_params` node; only ``disturbance_threshold`` is
        used here.

    Other Parameters
    ----------------
    growing_season_limit
        Minimum daily mean temperature for a day to count as within the growing
        season (degrees Celsius). This is a temperature gate, not a calendar
        one, so it needs no hemisphere correction: the seasonal phase is already
        carried by ``temperature``.

    Returns
    -------
    xr.DataArray
        Daily disturbance severity: the relative decline in GPP/LAI used to flag
        a disturbance, in [0, 1] where 0 is no disturbance and 1 is a total loss
        (dimensionless).
    """
    return _disturbances(
        temperature,
        gpp_obs,
        lai_obs,
        pft_params["disturbance_threshold"],
        growing_season_limit=growing_season_limit,
    )
