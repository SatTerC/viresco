"""
Viresco-compatible interface to PyRealm's 'SPLASH' model.

This module provides the `splash` node, which wraps PyRealm's SPLASH model to
calculate actual evapotranspiration (AET), soil moisture, and runoff from climate
inputs, and returns the physical fluxes pyrealm computes along the way.
"""

import warnings
from operator import attrgetter
from typing import Annotated, TypedDict, cast

import numpy as np
import pyrealm.constants
import pyrealm.core.calendar
import pyrealm.core.solar
import pyrealm.splash.splash
import xarray as xr
from catena.io import sole_time_dim
from hamilton.function_modifiers import config, extract_fields
from numpy.typing import NDArray
from pandas import DatetimeIndex
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from .._chunks import chunk_like
from ..temporal import DAILY, time_behaviour, time_index


class SplashOut(TypedDict):
    """Outputs of the `splash` node, at daily resolution."""

    actual_evapotranspiration: Annotated[DataArray, Unit("mm d-1"), DAILY]
    """Actual evapotranspiration: the daily water loss to the atmosphere
    (millimetres per day)."""
    soil_moisture: Annotated[DataArray, Unit("mm"), DAILY]
    """Soil moisture content at the end of the day (millimetres)."""
    runoff: Annotated[DataArray, Unit("mm"), DAILY]
    """Runoff: the soil-moisture overflow amount above capacity for the day
    (millimetres, an amount rather than a rate)."""
    potential_evapotranspiration: Annotated[DataArray, Unit("mm d-1"), DAILY]
    """Potential evapotranspiration: the water that *would* be lost to the
    atmosphere given the available energy, if soil moisture were not limiting
    (millimetres per day).

    SPLASH computes this on the way to actual evapotranspiration, by the
    Priestley-Taylor relation ``PET = (1 + k_w) * EET``, where equilibrium
    evapotranspiration follows from daytime net radiation and ``k_w = 0.26``. It
    is the demand term in an aridity index, which `viresco.models.pmodel` needs
    for ``method_kphio = "sandoval"``."""
    equilibrium_evapotranspiration: Annotated[DataArray, Unit("mm d-1"), DAILY]
    """Equilibrium evapotranspiration: the energy-limited loss from daytime net
    radiation, before the Priestley-Taylor scaling that gives potential
    evapotranspiration (millimetres per day)."""
    condensation: Annotated[DataArray, Unit("mm d-1"), DAILY]
    """Condensation, from nighttime net radiation (millimetres per day). With
    precipitation, this is the supply side of the daily water balance."""
    extraterrestrial_radiation: Annotated[DataArray, Unit("J m-2 d-1"), DAILY]
    """Solar radiation arriving at the top of the atmosphere over the day."""
    transmissivity: Annotated[DataArray, Unit("1"), DAILY]
    """Bulk atmospheric transmissivity, from sunshine fraction and elevation."""
    estimated_ppfd: Annotated[DataArray, Unit("mol m-2 d-1"), DAILY]
    """Photosynthetic photon flux density estimated from the radiation model.

    The units follow the calculation, which converts a daily radiation total.
    pyrealm's docstrings say micromoles per square metre per second, but its
    values are moles per square metre per day. This is a daily total, unlike the
    mean rate `viresco.models.pmodel` takes as ``ppfd``;
    `viresco.drivers.radiation` converts one to the other."""
    net_longwave_radiation: Annotated[DataArray, Unit("W m-2"), DAILY]
    """Net longwave radiation, as a rate that is constant over the day."""
    daytime_net_radiation: Annotated[DataArray, Unit("J m-2 d-1"), DAILY]
    """Net radiation over the hours when it is positive."""
    nighttime_net_radiation: Annotated[DataArray, Unit("J m-2 d-1"), DAILY]
    """Net radiation over the hours when it is negative, so this is negative."""


#: `SplashOut` field -> where pyrealm's `SplashModel` holds it. These are computed on
#: construction, independently of the soil moisture iteration, so are simply read off.
_FLUX_ATTRIBUTES = {
    "potential_evapotranspiration": "evap.pet_d",
    "equilibrium_evapotranspiration": "evap.eet_d",
    "condensation": "evap.cond",
    "extraterrestrial_radiation": "solar.daily_solar_radiation",
    "transmissivity": "solar.transmissivity",
    "estimated_ppfd": "solar.daily_ppfd",
    "net_longwave_radiation": "solar.net_longwave_radiation",
    "daytime_net_radiation": "solar.daytime_net_radiation",
    "nighttime_net_radiation": "solar.nighttime_net_radiation",
}

#: `SplashOut` fields, in the order `_splash_block` returns them.
_OUTPUT_FIELDS = (
    "actual_evapotranspiration",
    "soil_moisture",
    "runoff",
    *_FLUX_ATTRIBUTES,
)

#: Elevations beyond these are not land surface, so are likely an undeclared fill value.
_PLAUSIBLE_ELEVATION_M = (-500.0, 9000.0)

#: How many cells an error or warning lists before truncating.
_MAX_CELLS_NAMED = 10


def _describe_cells(labels: NDArray) -> str:
    """Name up to `_MAX_CELLS_NAMED` cells in an error or warning."""
    named = ", ".join(str(label) for label in labels[:_MAX_CELLS_NAMED])
    more = ", ..." if labels.size > _MAX_CELLS_NAMED else ""
    return f"{labels.size} cell(s) ({named}{more})"


def _cell_labels(time: str, *arrays: DataArray) -> DataArray:
    """Label each cell of ``arrays``' non-time dimensions for `_describe_cells`.

    A cell on one dimension is named by its coordinate value, as a site or an
    index; a cell on several by ``dim=value`` for each, as ``y=50.0
    x=-2.0``. A dimension with no coordinate gives its position instead.
    """
    template = xr.broadcast(
        *(a.isel({time: 0}, drop=True) if time in a.dims else a for a in arrays)
    )[0]
    dims = [str(dim) for dim in template.dims]
    axes = [
        template[dim].values if dim in template.coords else np.arange(size)
        for dim, size in template.sizes.items()
    ]
    labels = np.empty(template.shape, dtype=object)
    for index in np.ndindex(template.shape):
        values = [axis[i] for axis, i in zip(axes, index, strict=True)]
        labels[index] = (
            str(values[0])
            if len(values) == 1
            else " ".join(
                f"{dim}={value}" for dim, value in zip(dims, values, strict=True)
            )
        )
    return chunk_like(
        xr.DataArray(labels, dims=template.dims, coords=template.coords), *arrays
    )


def _require_consecutive_days(dates: DatetimeIndex) -> None:
    """Raise if ``dates`` is not one sample per day without gaps.

    pyrealm takes its time steps by position, so it would run across a gap in the
    calendar as if the days on either side were adjacent.
    """
    breaks = np.flatnonzero(np.diff(dates.values) != np.timedelta64(1, "D"))
    if breaks.size:
        before, after = dates[breaks[0] : breaks[0] + 2].strftime("%Y-%m-%d")
        raise ValueError(
            f"SPLASH needs one input per day with no gaps, but found {breaks.size} "
            f"break(s), the first from {before} to {after}."
        )


def _spin_up(
    model: pyrealm.splash.splash.SplashModel, max_iter: int, max_diff: float
) -> NDArray[np.float64]:
    """Estimate initial soil moisture, allowing for every cell being NaN.

    pyrealm's convergence test ignores NaN cells until there are no others, and then
    reports that it failed to converge with a difference of NaN. That only matters to a
    block where pyrealm's calculation gives NaN for every cell, which should get the
    same outcome as it would in a block with other cells.
    """
    try:
        return model.estimate_initial_soil_moisture(
            max_iter=max_iter, max_diff=max_diff, verbose=False
        )
    except RuntimeError:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            one_year = model.estimate_initial_soil_moisture(
                max_iter=1, return_convergence=True
            )
        if np.isnan(one_year).all():
            return one_year[-1]
        raise


def _run_pyrealm(
    sf: NDArray[np.float64],
    tc: NDArray[np.float64],
    pn: NDArray[np.float64],
    elevation: NDArray[np.float64],
    latitude: NDArray[np.float64],
    capacity: NDArray[np.float64],
    initial_soil_moisture: NDArray[np.float64] | None,
    *,
    dates: pyrealm.core.calendar.Calendar,
    max_iter: int,
    max_diff: float,
) -> tuple[NDArray[np.float64], ...]:
    """Run SPLASH on ``(time, cell)`` arrays, in the order of `_OUTPUT_FIELDS`.

    ``lat``/``elv`` go in as ``(1, cell)``: they pass through ``check_input_shapes``,
    which demands equal ndim with the climate arrays, then ``broadcast_time``. ``kWm``
    goes in as ``(cell,)``: it is neither time-broadcast nor shape-checked, and a 2D
    value corrupts the per-day spatial shape.
    """
    model = pyrealm.splash.splash.SplashModel(
        lat=latitude[np.newaxis],
        elv=elevation[np.newaxis],
        sf=sf,
        tc=tc,
        pn=pn,
        dates=dates,
        kWm=capacity,
    )
    # BUG: pyrealm 2.0.0 does not pass kWm on to its evaporative fluxes, which would
    # leave the supply rate in AET using a capacity of 150 mm whatever is configured.
    model.evap.kWm = model.kWm

    if initial_soil_moisture is None:
        initial_soil_moisture = _spin_up(model, max_iter=max_iter, max_diff=max_diff)
    states = model.calculate_soil_moisture(initial_soil_moisture)
    fluxes = (attrgetter(name)(model) for name in _FLUX_ATTRIBUTES.values())
    return (*states, *fluxes)


def _splash_block(
    sunshine_fraction: NDArray[np.float64],
    temperature: NDArray[np.float64],
    precipitation: NDArray[np.float64],
    elevation: NDArray[np.float64],
    latitude: NDArray[np.float64],
    max_soil_moisture: NDArray[np.float64],
    cell_labels: NDArray,
    initial_soil_moisture: NDArray[np.float64] | None = None,
    *,
    dates: pyrealm.core.calendar.Calendar,
    max_iter: int,
    max_diff: float,
) -> tuple[NDArray[np.float64], ...]:
    """Run SPLASH on a whole block, deciding each cell from its own inputs.

    ``apply_ufunc`` places the ``time`` core dim last and hands every input the
    block's other dimensions, however many there are, possibly as length-1 axes.
    Those are broadcast together and flattened into one axis of cells here,
    because the masked cells have to be picked out before pyrealm sees the rest;
    the outputs are put back on the block's shape, with ``time`` last, in the
    order of `_OUTPUT_FIELDS`.

    A cell's outcome must not depend on which other cells share its block, or the
    outcome would change with the block size:

    - Masked: a NaN static or initial state, or no climate data at all. The output is
      NaN, and pyrealm never sees the cell.
    - Gap: some climate values are missing. This raises, because soil moisture carries
      over from one day to the next, so everything after the gap would be lost.
    - Model failure: complete inputs but NaN soil moisture. The output is NaN and this
      warns, because a rare failure in pyrealm should not stop a large run.
    """
    climate_in = [
        np.asarray(values, dtype=float)
        for values in (sunshine_fraction, temperature, precipitation)
    ]
    static_in = [
        np.asarray(values, dtype=float)
        for values in (elevation, latitude, max_soil_moisture)
    ] + (
        []
        if initial_soil_moisture is None
        else [np.asarray(initial_soil_moisture, dtype=float)]
    )
    n_days = climate_in[0].shape[-1]
    shape = np.broadcast_shapes(
        *(values.shape[:-1] for values in climate_in),
        *(values.shape for values in static_in),
        np.shape(cell_labels),
    )
    n_cells = int(np.prod(shape))
    climate = np.stack(
        [
            np.broadcast_to(values, (*shape, n_days)).reshape(n_cells, n_days).T
            for values in climate_in
        ]
    )
    statics = np.stack(
        [np.broadcast_to(values, shape).reshape(n_cells) for values in static_in]
    )
    labels = np.broadcast_to(cell_labels, shape).reshape(n_cells)

    missing = np.isnan(climate)
    masked = missing.all(axis=(0, 1)) | np.isnan(statics).any(axis=0)
    gaps = missing.any(axis=(0, 1)) & ~masked
    if gaps.any():
        raise ValueError(
            "SPLASH inputs have missing values in "
            f"{_describe_cells(labels[gaps])}. Soil moisture carries over from "
            "day to day, so everything after a gap would be lost. Fill the gaps, or "
            "mask each cell by making all of its climate inputs NaN."
        )

    outputs = np.full((len(_OUTPUT_FIELDS), n_cells, n_days), np.nan)
    valid = ~masked
    if not valid.any():
        return tuple(output.reshape(*shape, n_days) for output in outputs)

    low, high = _PLAUSIBLE_ELEVATION_M
    implausible = valid & ((statics[0] < low) | (statics[0] > high))
    if implausible.any():
        warnings.warn(
            f"Elevation is outside {low:g} to {high:g} m in "
            f"{_describe_cells(labels[implausible])}, which suggests an "
            "undeclared fill value. SPLASH will still use these values.",
            stacklevel=2,
        )

    sf, tc, pn = climate[:, :, valid]
    elv, lat, capacity = statics[:3, valid]
    results = _run_pyrealm(
        sf,
        tc,
        pn,
        elv,
        lat,
        capacity,
        statics[3, valid] if initial_soil_moisture is not None else None,
        dates=dates,
        max_iter=max_iter,
        max_diff=max_diff,
    )
    for output, result in zip(outputs, results, strict=True):
        output[valid] = np.moveaxis(result, 0, -1)

    moisture = outputs[_OUTPUT_FIELDS.index("soil_moisture")]
    failed = valid & np.isnan(moisture).any(axis=-1)
    if failed.any():
        warnings.warn(
            "SPLASH returned NaN soil moisture for "
            f"{_describe_cells(labels[failed])} despite complete inputs. "
            "pyrealm's AET calculation can fail at high latitudes.",
            stacklevel=2,
        )
    return tuple(output.reshape(*shape, n_days) for output in outputs)


def _splash(
    sunshine_fraction: DataArray,
    temperature: DataArray,
    precipitation: DataArray,
    elevation: DataArray,
    latitude: DataArray,
    max_soil_moisture: DataArray,
    dates: DatetimeIndex,
    *,
    soil_moisture_init_max_iter: int,
    soil_moisture_init_max_diff: float,
    initial_soil_moisture: DataArray | None = None,
) -> SplashOut:
    """Apply SPLASH over a block via `xarray.apply_ufunc`.

    SPLASH is sequential along time (soil moisture carries state day to day) but
    embarrassingly parallel over space, so time is the input/output core dim and
    every other dimension, whatever there is of it, is broadcast (mapped).
    ``vectorize`` is left ``False`` so the whole block reaches pyrealm in one call
    and is vectorised internally; with ``dask="parallelized"`` a future dask
    backend can still chunk over space.
    Unset, ``initial_soil_moisture`` means the initial state comes from the spin-up.
    """
    _require_consecutive_days(dates)
    time = sole_time_dim(temperature, "temperature")
    prescribed = [] if initial_soil_moisture is None else [initial_soil_moisture]
    calendar = pyrealm.core.calendar.Calendar(dates.values)

    n_outputs = len(_OUTPUT_FIELDS)
    outputs = xr.apply_ufunc(
        _splash_block,
        sunshine_fraction,
        temperature,
        precipitation,
        elevation,
        latitude,
        max_soil_moisture,
        _cell_labels(
            time,
            sunshine_fraction,
            temperature,
            precipitation,
            elevation,
            latitude,
            max_soil_moisture,
        ),
        *prescribed,
        input_core_dims=[[time]] * 3 + [[]] * (4 + len(prescribed)),
        output_core_dims=[[time]] * n_outputs,
        kwargs={
            "dates": calendar,
            "max_iter": soil_moisture_init_max_iter,
            "max_diff": soil_moisture_init_max_diff,
        },
        dask="parallelized",
        keep_attrs=False,
        output_dtypes=[float] * n_outputs,
    )

    # apply_ufunc drops the time coord (a core dim) and puts time last; reattach
    # the coord and put time first.
    time_coord = temperature.coords[time]
    return cast(
        SplashOut,
        {
            name: out.assign_coords({time: time_coord}).transpose(time, ...)
            for name, out in zip(_OUTPUT_FIELDS, outputs, strict=True)
        },
    )


_INIT_METHODS = ("equilibrate", "prescribed")


@config.when_not_in(soil_moisture_init_method=["prescribed"])
def soil_moisture_init_inputs__equilibrate() -> dict[str, DataArray]:
    """No extra inputs, for ``soil_moisture_init_method = "equilibrate"``."""
    return {}


@config.when_in(soil_moisture_init_method=["prescribed"])
@check_annotations
def soil_moisture_init_inputs__prescribed(
    initial_soil_moisture: Annotated[DataArray, Unit("mm")],
) -> dict[str, DataArray]:
    """Supply the starting state, for ``soil_moisture_init_method = "prescribed"``.

    Parameters
    ----------
    initial_soil_moisture
        Soil moisture on the day before the first date (millimetres), one value
        per cell, between 0 and ``max_soil_moisture``.
    """
    return {"initial_soil_moisture": initial_soil_moisture}


_SUNSHINE_FRACTION_METHODS = ("input", "shortwave")

#: A daily mean irradiance in W m-2 to a daily total in J m-2 d-1.
_SECONDS_PER_DAY = 86400.0


def _extraterrestrial_radiation(
    latitude: DataArray, dates: DatetimeIndex, time: str
) -> DataArray:
    """Daily radiation at the top of the atmosphere (J m-2), as pyrealm computes it."""
    const = pyrealm.constants.CoreConst()
    calendar = pyrealm.core.calendar.Calendar(dates.values)
    nu, lambda_ = pyrealm.core.solar.calculate_heliocentric_longitudes(
        ordinal_date=calendar.julian_day, n_days=calendar.days_in_year
    )
    by_day = {"coords": {time: dates}, "dims": time}
    distance_factor = xr.DataArray(
        pyrealm.core.solar.calculate_distance_factor(
            nu, solar_eccentricity=const.solar_eccentricity
        ),
        **by_day,
    )
    declination = xr.DataArray(
        pyrealm.core.solar.calculate_solar_declination_angle(
            lambda_, solar_obliquity=const.solar_obliquity
        ),
        **by_day,
    )

    def radiation(
        distance_factor: NDArray[np.float64],
        declination: NDArray[np.float64],
        latitude: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        return pyrealm.core.solar.calculate_daily_solar_radiation(
            distance_factor=distance_factor,
            sunset_hour_angle=pyrealm.core.solar.calculate_sunset_hour_angle(
                declination=declination, latitude=latitude
            ),
            declination=declination,
            latitude=latitude,
            day_seconds=const.day_seconds,
            solar_constant=const.solar_constant,
        )

    return xr.apply_ufunc(radiation, distance_factor, declination, latitude)


@config.when_in(sunshine_fraction_method=["shortwave"])
@check_annotations
@stamp_output_units(overwrite=True)
def sunshine_fraction__shortwave(
    shortwave_radiation: Annotated[DataArray, Unit("W m-2"), DAILY],
    elevation: Annotated[DataArray, Unit("m")],
    latitude: Annotated[DataArray, Unit("degrees")],
) -> Annotated[DataArray, Unit("1"), DAILY]:
    """Recover sunshine fraction from measured shortwave radiation.

    For ``sunshine_fraction_method = "shortwave"``. SPLASH models the shortwave
    radiation reaching the ground as ``tau * R_a``, where ``R_a`` is the radiation
    at the top of the atmosphere and the transmissivity ``tau = (c + d * sf) *
    (1 + f * elevation)`` (Linacre, 1968). This inverts that relation, with
    pyrealm's own ``R_a`` and coefficients, so SPLASH's modelled shortwave
    reproduces the measurement wherever the result lies in 0-1.

    The result is clipped to 0-1. Overcast days whose transmissivity is below
    ``c`` (0.25) clip to 0, so on those SPLASH overestimates shortwave; in the UK
    that can be a third of winter days. Sunshine fraction also sets SPLASH's net
    longwave radiation, which therefore follows from this value rather than from
    any longwave measurement.

    Parameters
    ----------
    shortwave_radiation
        Incoming shortwave radiation at the surface, as a mean over the day
        (watts per square metre), with no gaps.
    elevation
        Elevation of the site (metres).
    latitude
        Latitude of the site (degrees).
    """
    c, d, f = pyrealm.constants.CoreConst().transmissivity_coef
    time = sole_time_dim(shortwave_radiation, "shortwave_radiation")
    extraterrestrial = _extraterrestrial_radiation(
        latitude,
        time_index(shortwave_radiation, "shortwave_radiation"),
        time,
    )
    transmissivity = shortwave_radiation * _SECONDS_PER_DAY / extraterrestrial
    return ((transmissivity / (1 + f * elevation) - c) / d).clip(0, 1)


@extract_fields()
@time_behaviour("stateful")
@check_annotations
@stamp_output_units
def splash(
    sunshine_fraction: Annotated[DataArray, Unit("1"), DAILY],
    temperature: Annotated[DataArray, Unit("degC"), DAILY],
    precipitation: Annotated[DataArray, Unit("mm d-1"), DAILY],
    elevation: Annotated[DataArray, Unit("m")],
    latitude: Annotated[DataArray, Unit("degrees")],
    max_soil_moisture: Annotated[DataArray, Unit("mm")],
    soil_moisture_init_inputs: dict[str, DataArray],
    *,
    sunshine_fraction_method: str = "input",
    soil_moisture_init_method: str = "equilibrate",
    soil_moisture_init_max_iter: int = 10,
    soil_moisture_init_max_diff: float = 1.0,
) -> SplashOut:
    """Run the SPLASH water balance model.

    The daily calendar SPLASH needs is read off ``temperature``'s time
    coordinate, and must have no missing days.

    Parameters
    ----------
    sunshine_fraction
        Fraction of daylight hours that are sunny (dimensionless, 0-1). An input
        unless ``sunshine_fraction_method`` derives it.
    temperature
        Daily mean air temperature (degrees Celsius).
    precipitation
        Precipitation (millimetres per day).
    elevation
        Elevation of the site (metres). Values outside -500 to 9000 warn, as they
        suggest an undeclared fill value.
    latitude
        Latitude of the site (degrees).
    max_soil_moisture
        Maximum soil moisture capacity (millimetres). Sets the runoff threshold and
        scales the rate at which the soil supplies water for evaporation.
    soil_moisture_init_inputs
        Extra inputs for the configured ``soil_moisture_init_method``.

    Other Parameters
    ----------------
    sunshine_fraction_method
        Where ``sunshine_fraction`` comes from: ``input`` reads it as an
        input, and ``shortwave`` recovers it from measured shortwave radiation;
        see `sunshine_fraction__shortwave`.
    soil_moisture_init_method
        Where the initial soil moisture comes from: ``equilibrate`` repeats the
        first year until soil moisture stabilises, and ``prescribed`` takes it
        from the ``initial_soil_moisture`` input; see
        `soil_moisture_init_inputs__prescribed`.
    soil_moisture_init_max_iter
        Maximum number of one-year iterations used to estimate initial soil
        moisture. If any cell in a block with a non-NaN result has not converged
        by then, the run stops with an error. Only used by ``equilibrate``.
    soil_moisture_init_max_diff
        Maximum acceptable difference between year-start and year-end soil
        moisture (millimetres). Only used by ``equilibrate``.

    Returns
    -------
    SplashOut
        Dictionary of daily outputs:

        - actual_evapotranspiration: actual evapotranspiration
          (millimetres per day)
        - soil_moisture: soil moisture content (millimetres)
        - runoff: runoff overflow amount (millimetres)
        - potential_evapotranspiration: energy-limited water demand
          (millimetres per day)
        - equilibrium_evapotranspiration, condensation: the other
          water fluxes (millimetres per day)
        - extraterrestrial_radiation, transmissivity,
          estimated_ppfd, net_longwave_radiation,
          daytime_net_radiation, nighttime_net_radiation: the
          radiation fluxes

        See `SplashOut` for per-output detail.

    Raises
    ------
    ValueError
        If ``sunshine_fraction_method`` or ``soil_moisture_init_method`` is not a
        known method. Without this a misspelt ``prescribed`` would silently select
        ``equilibrate``.
    """
    if sunshine_fraction_method not in _SUNSHINE_FRACTION_METHODS:
        raise ValueError(
            f"Unknown sunshine_fraction_method {sunshine_fraction_method!r}; "
            f"expected one of {', '.join(map(repr, _SUNSHINE_FRACTION_METHODS))}."
        )
    if soil_moisture_init_method not in _INIT_METHODS:
        raise ValueError(
            f"Unknown soil_moisture_init_method {soil_moisture_init_method!r}; "
            f"expected one of {', '.join(map(repr, _INIT_METHODS))}."
        )
    return _splash(
        sunshine_fraction=sunshine_fraction,
        temperature=temperature,
        precipitation=precipitation,
        elevation=elevation,
        latitude=latitude,
        max_soil_moisture=max_soil_moisture,
        dates=time_index(temperature, "temperature"),
        initial_soil_moisture=soil_moisture_init_inputs.get("initial_soil_moisture"),
        soil_moisture_init_max_iter=soil_moisture_init_max_iter,
        soil_moisture_init_max_diff=soil_moisture_init_max_diff,
    )
