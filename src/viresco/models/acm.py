"""The Aggregated Canopy Model (ACM), version 1, of Williams et al. (1997).

ACM predicts daily gross primary productivity (GPP) from leaf area index, foliar
nitrogen, daily temperature extremes, irradiance, atmospheric CO2, canopy height,
the soil-to-leaf water potential difference and the day of year. It was derived
as a ten-parameter emulator of a multilayer soil-plant-atmosphere canopy model,
and carries no state between days.

Having no state, ACM is a set of nodes rather than one node around a kernel,
split where the later variants of ACM differ from version 1: the
nitrogen-limited capacity, the canopy conductance and the seasonal correction
are each a node that a variant can replace, and `acm` combines them. Written
here from the equations of the paper; see the model page for the theory and
where viresco departs from it.

Williams, M., Rastetter, E. B., Fernandes, D. N., Goulden, M. L., Shaver, G. R.
and Johnson, L. C. (1997). Predicting gross primary productivity in terrestrial
ecosystems. Ecological Applications 7(3), 882-894.
"""

from typing import Annotated, TypedDict

import numpy as np
import xarray as xr
from catena.io import sole_time_dim
from hamilton.function_modifiers import extract_fields
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from ..temporal import DAILY, time_index

#: Day of year of the June solstice, the paper's midsummer (22 June).
_MIDSUMMER_NORTH = 173
#: Day of year of the December solstice, midsummer in the southern hemisphere.
_MIDSUMMER_SOUTH = 355
#: Days from midsummer used everywhere in the tropics, as the paper prescribes.
_TROPICAL_DAYS_FROM_MIDSUMMER = 80.0
#: Latitude of the tropics of Cancer and Capricorn (degrees).
_TROPIC_LATITUDE = 23.44
#: Daily mean irradiance in W m-2 to a daily total in MJ m-2 d-1.
_W_M2_TO_MJ_M2_D = 86400.0 / 1e6


def _time_first(da: DataArray, like: DataArray, name: str) -> DataArray:
    return da.transpose(sole_time_dim(like, name), ...)


@check_annotations
@stamp_output_units
def acm_days_from_midsummer(
    latitude: Annotated[DataArray, Unit("degrees")],
    lai_obs: Annotated[DataArray, DAILY],
) -> Annotated[DataArray, Unit("d"), DAILY]:
    """Days from midsummer, the calendar driver of ACM's seasonal correction.

    The distance in days, around the calendar, from the day of year to the
    summer solstice of the cell's hemisphere: day 173 in the north, day 355 in
    the south. Within the tropics it is 80 throughout, as Williams et al. (1997)
    prescribe, removing the correction's seasonal variation.

    Parameters
    ----------
    latitude
        Latitude of each cell (degrees north).
    lai_obs
        Read only for its daily time coordinate, which sets the returned
        series' calendar.

    Returns
    -------
    DataArray
        Days from midsummer, on ``time`` then ``latitude``'s dimensions.
    """
    time = sole_time_dim(lai_obs, "lai_obs")
    dates = time_index(lai_obs, "lai_obs")
    day_of_year = xr.DataArray(dates.day_of_year, coords={time: dates}, dims=time)
    midsummer = xr.where(latitude >= 0, _MIDSUMMER_NORTH, _MIDSUMMER_SOUTH)
    distance = abs(day_of_year - midsummer)
    distance = np.minimum(distance, 365 - distance)
    result = xr.where(
        abs(latitude) < _TROPIC_LATITUDE, _TROPICAL_DAYS_FROM_MIDSUMMER, distance
    ).astype(float)
    result.attrs.clear()
    return result.transpose(time, ...)


@check_annotations
@stamp_output_units(overwrite=True)
def acm_nitrogen_limited_capacity(
    lai_obs: Annotated[DataArray, Unit("1"), DAILY],
    max_temperature: Annotated[DataArray, Unit("degC"), DAILY],
    min_temperature: Annotated[DataArray, Unit("degC"), DAILY],
    *,
    acm_foliar_nitrogen: float = 1.92,
    acm_nue: float = 2.95,
    acm_nue_temperature_coefficient: float = 0.018,
) -> Annotated[DataArray, Unit("g m-2 d-1"), DAILY]:
    """Canopy photosynthetic capacity limited by nitrogen and temperature.

    Eq. 2 of Williams et al. (1997): proportional to total canopy nitrogen,
    foliar nitrogen times LAI, with an exponential response to the daily mean
    temperature.

    Parameters
    ----------
    lai_obs
        Observed leaf area index (square metres of leaf per square metre of
        ground).
    max_temperature
        Daily maximum air temperature (degrees Celsius).
    min_temperature
        Daily minimum air temperature (degrees Celsius).

    Other Parameters
    ----------------
    acm_foliar_nitrogen
        Mean foliar nitrogen concentration, N (grams of nitrogen per square
        metre of leaf).
    acm_nue
        Nitrogen-use efficiency parameter, a1 (grams of carbon per gram of
        nitrogen per day).
    acm_nue_temperature_coefficient
        Temperature coefficient of nitrogen-use efficiency, a2 (per degree
        Celsius).

    Returns
    -------
    DataArray
        Nitrogen-limited capacity, p_N (grams of carbon per square metre per
        day).
    """
    mean_temperature = 0.5 * (max_temperature + min_temperature)
    capacity = (
        acm_nue
        * acm_foliar_nitrogen
        * lai_obs
        * xr.ufuncs.exp(acm_nue_temperature_coefficient * mean_temperature)
    )
    return _time_first(capacity, lai_obs, "lai_obs")


@check_annotations
@stamp_output_units(overwrite=True)
def acm_canopy_conductance(
    max_temperature: Annotated[DataArray, Unit("degC"), DAILY],
    min_temperature: Annotated[DataArray, Unit("degC"), DAILY],
    *,
    acm_canopy_height: float = 24.0,
    acm_water_potential_difference: float = -2.5,
    acm_conductance_temperature_coefficient: float = -0.029,
    acm_conductance_height_coefficient: float = 0.315,
) -> Annotated[DataArray, Unit("g m-2 d-1 ppm-1"), DAILY]:
    """Canopy conductance to CO2.

    Eq. 5 of Williams et al. (1997): increasing with the soil-to-leaf water
    potential difference, and falling with temperature, canopy height and the
    daily temperature range. An empirical aggregate rather than a physiological
    conductance: its unit is whatever turns a CO2 concentration difference into
    a carbon flux (eq. 4).

    Parameters
    ----------
    max_temperature
        Daily maximum air temperature (degrees Celsius).
    min_temperature
        Daily minimum air temperature (degrees Celsius).

    Other Parameters
    ----------------
    acm_canopy_height
        Canopy height, H (metres).
    acm_water_potential_difference
        Difference between minimum leaf water potential and soil water
        potential, Psi_d (megapascals). Negative; more negative means wetter
        soil.
    acm_conductance_temperature_coefficient
        Temperature coefficient of canopy conductance, b1 (per degree Celsius).
    acm_conductance_height_coefficient
        Coefficient of canopy height in canopy conductance, b2 (degrees Celsius
        per metre). Table 2 names it the temperature range constant of canopy
        conductance.

    Returns
    -------
    DataArray
        Canopy conductance, g_c (grams of carbon per square metre per day per
        part per million).
    """
    if acm_water_potential_difference >= 0:
        raise ValueError(
            "acm_water_potential_difference must be negative (leaf water potential "
            f"below soil water potential); got {acm_water_potential_difference}."
        )
    mean_temperature = 0.5 * (max_temperature + min_temperature)
    temperature_range = 0.5 * (max_temperature - min_temperature)
    conductance = (
        -acm_water_potential_difference
        * xr.ufuncs.exp(acm_conductance_temperature_coefficient * mean_temperature)
        / (acm_conductance_height_coefficient * acm_canopy_height + temperature_range)
    )
    return _time_first(conductance, max_temperature, "max_temperature")


@check_annotations
@stamp_output_units(overwrite=True)
def acm_seasonal_factor(
    acm_days_from_midsummer: Annotated[DataArray, Unit("d"), DAILY],
    *,
    acm_day_length_coefficient: float = -0.0018,
    acm_day_length_constant: float = 1.81,
) -> Annotated[DataArray, Unit("1"), DAILY]:
    """Seasonal correction to light- and CO2-limited photosynthesis.

    The factor in eq. 9 of Williams et al. (1997), linear in the number of days
    from midsummer. Daily irradiance already carries most of the effect of
    season, but GPP responds nonlinearly to it, so long days are more
    productive than short ones with the same total.

    Parameters
    ----------
    acm_days_from_midsummer
        Days from the summer solstice of the cell's hemisphere (days). Output of
        the `acm_days_from_midsummer` node.

    Other Parameters
    ----------------
    acm_day_length_coefficient
        Day length constant, d1 (per day).
    acm_day_length_constant
        Midsummer coefficient, d2 (dimensionless).

    Returns
    -------
    DataArray
        Seasonal factor (dimensionless).
    """
    return (
        acm_day_length_coefficient * acm_days_from_midsummer + acm_day_length_constant
    )


class AcmOut(TypedDict):
    """Outputs of the `acm` node, at daily resolution."""

    gpp: Annotated[DataArray, Unit("g m-2 d-1"), DAILY]
    """Gross primary productivity: carbon fixed per unit ground area per day
    (grams of carbon per square metre per day)."""
    internal_co2: Annotated[DataArray, Unit("ppm"), DAILY]
    """CO2 concentration at the site of carboxylation, solved from the balance of
    metabolic and diffusive supply (micromoles per mole)."""


@extract_fields()
@check_annotations
@stamp_output_units(overwrite=True)
def acm(
    acm_nitrogen_limited_capacity: Annotated[DataArray, Unit("g m-2 d-1"), DAILY],
    acm_canopy_conductance: Annotated[DataArray, Unit("g m-2 d-1 ppm-1"), DAILY],
    acm_seasonal_factor: Annotated[DataArray, Unit("1"), DAILY],
    lai_obs: Annotated[DataArray, Unit("1"), DAILY],
    shortwave_radiation: Annotated[DataArray, Unit("W m-2"), DAILY],
    co2: Annotated[DataArray, Unit("ppm"), DAILY],
    *,
    acm_co2_compensation_point: float = 32.6,
    acm_co2_half_saturation: float = 576.7,
    acm_max_quantum_yield: float = 0.989,
    acm_quantum_yield_lai_coefficient: float = 0.873,
) -> AcmOut:
    """
    Run the Aggregated Canopy Model, version 1 (Williams et al., 1997).

    Solves for the internal CO2 concentration at which metabolic and diffusive
    supply balance (eqs. 3, 4 and 6), co-limits the result by light (eqs. 7 and
    8), and applies the seasonal correction (eq. 9). The calibrated parameters
    default to Table 2 of the paper.

    Parameters
    ----------
    acm_nitrogen_limited_capacity
        Nitrogen-limited photosynthetic capacity, p_N (grams of carbon per
        square metre per day). Output of the `acm_nitrogen_limited_capacity`
        node.
    acm_canopy_conductance
        Canopy conductance, g_c (grams of carbon per square metre per day per
        part per million). Output of the `acm_canopy_conductance` node.
    acm_seasonal_factor
        Seasonal correction factor (dimensionless). Output of the
        `acm_seasonal_factor` node.
    lai_obs
        Observed leaf area index (square metres of leaf per square metre of
        ground).
    shortwave_radiation
        Daily mean downwelling shortwave radiation at the surface (watts per
        square metre).
    co2
        Atmospheric CO2 concentration (parts per million).

    Other Parameters
    ----------------
    acm_co2_compensation_point
        Canopy CO2 compensation point, theta (micromoles per mole).
    acm_co2_half_saturation
        Canopy CO2 half-saturation point, k (micromoles per mole).
    acm_max_quantum_yield
        Maximum canopy quantum yield, c1 (grams of carbon per megajoule).
    acm_quantum_yield_lai_coefficient
        LAI-canopy quantum yield coefficient, c2 (dimensionless).

    Returns
    -------
    AcmOut
        Daily GPP and internal CO2 concentration; see `AcmOut`.
    """
    q = acm_co2_compensation_point - acm_co2_half_saturation
    p = acm_nitrogen_limited_capacity / acm_canopy_conductance
    b = co2 + q - p
    internal_co2 = 0.5 * (
        b + xr.ufuncs.sqrt(b**2 - 4.0 * (co2 * q - p * acm_co2_compensation_point))
    )
    diffusion_limited = acm_canopy_conductance * (co2 - internal_co2)
    quantum_yield = (
        acm_max_quantum_yield
        * lai_obs**2
        / (acm_quantum_yield_lai_coefficient + lai_obs**2)
    )
    light = quantum_yield * shortwave_radiation * _W_M2_TO_MJ_M2_D
    denominator = light + diffusion_limited
    with np.errstate(invalid="ignore", divide="ignore"):
        # Zero LAI zeroes both terms; GPP is then zero, not 0/0.
        light_limited = xr.where(
            denominator == 0.0, 0.0, light * diffusion_limited / denominator
        )
    gpp = light_limited * acm_seasonal_factor
    return {
        "gpp": _time_first(gpp, lai_obs, "lai_obs"),
        "internal_co2": _time_first(internal_co2, lai_obs, "lai_obs"),
    }
