"""The Aggregated Canopy Model (ACM), version 1, of Williams et al. (1997).

ACM predicts daily gross primary productivity (GPP) from leaf area index, foliar
nitrogen, daily temperature extremes, irradiance, atmospheric CO2, canopy height,
the soil-to-leaf water potential difference and the day of year. It was derived
as a ten-parameter emulator of a multilayer soil-plant-atmosphere canopy model,
and carries no state between days.

Written here from the equations of the paper; see the model page for the theory
and where viresco departs from it.

Williams, M., Rastetter, E. B., Fernandes, D. N., Goulden, M. L., Shaver, G. R.
and Johnson, L. C. (1997). Predicting gross primary productivity in terrestrial
ecosystems. Ecological Applications 7(3), 882-894.
"""

from typing import Annotated, TypedDict, cast

import numpy as np
import xarray as xr
from catena.io import sole_time_dim
from hamilton.function_modifiers import extract_fields
from numpy.typing import NDArray
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


class AcmOut(TypedDict):
    """Outputs of the `acm` node, at daily resolution."""

    gpp: Annotated[DataArray, Unit("g m-2 d-1"), DAILY]
    """Gross primary productivity: carbon fixed per unit ground area per day
    (grams of carbon per square metre per day)."""
    internal_co2: Annotated[DataArray, Unit("ppm"), DAILY]
    """CO2 concentration at the site of carboxylation, solved from the balance of
    metabolic and diffusive supply (micromoles per mole)."""


_ACM_OUTPUT_NAMES: tuple[str, ...] = tuple(AcmOut.__annotations__)


def _acm_kernel(
    lai: NDArray[np.float64],
    max_temperature: NDArray[np.float64],
    min_temperature: NDArray[np.float64],
    irradiance: NDArray[np.float64],
    co2: NDArray[np.float64],
    days_from_midsummer: NDArray[np.float64],
    *,
    foliar_nitrogen: float,
    canopy_height: float,
    water_potential_difference: float,
    nue: float,
    nue_temperature_coefficient: float,
    co2_compensation_point: float,
    co2_half_saturation: float,
    conductance_temperature_coefficient: float,
    conductance_height_coefficient: float,
    max_quantum_yield: float,
    quantum_yield_lai_coefficient: float,
    day_length_coefficient: float,
    day_length_constant: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Evaluate ACM element by element on broadcastable numpy arrays.

    ``irradiance`` is the daily total in MJ m-2 d-1. Returns GPP (g m-2 d-1) and
    the internal CO2 concentration (ppm). Equation numbers are the paper's.
    """
    mean_temperature = 0.5 * (max_temperature + min_temperature)
    temperature_range = 0.5 * (max_temperature - min_temperature)

    # Eq. 2: nitrogen- and temperature-limited photosynthetic capacity.
    p_n = (
        nue
        * foliar_nitrogen
        * lai
        * np.exp(nue_temperature_coefficient * mean_temperature)
    )
    # Eq. 5: canopy conductance.
    g_c = (
        -water_potential_difference
        * np.exp(conductance_temperature_coefficient * mean_temperature)
        / (conductance_height_coefficient * canopy_height + temperature_range)
    )
    # Eq. 6: internal CO2 where metabolic (eq. 3) and diffusive (eq. 4) supply meet.
    q = co2_compensation_point - co2_half_saturation
    p = p_n / g_c
    b = co2 + q - p
    c_i = 0.5 * (b + np.sqrt(b**2 - 4.0 * (co2 * q - p * co2_compensation_point)))
    # Eq. 4: diffusion-limited rate.
    p_d = g_c * (co2 - c_i)
    # Eqs. 7-8: co-limitation by light, with a canopy quantum yield set by LAI.
    e_0 = max_quantum_yield * lai**2 / (quantum_yield_lai_coefficient + lai**2)
    light = e_0 * irradiance
    denominator = light + p_d
    with np.errstate(invalid="ignore", divide="ignore"):
        # Zero LAI zeroes both terms; GPP is then zero, not 0/0.
        p_i = np.where(denominator == 0.0, 0.0, light * p_d / denominator)
    # Eq. 9: day-of-year correction.
    gpp = p_i * (day_length_coefficient * days_from_midsummer + day_length_constant)
    return gpp, c_i


def _acm(
    lai_obs: DataArray,
    max_temperature: DataArray,
    min_temperature: DataArray,
    shortwave_radiation: DataArray,
    co2: DataArray,
    days_from_midsummer: DataArray,
    **settings: float,
) -> AcmOut:
    """Map `_acm_kernel` over every cell and day.

    ACM is algebraic in each day's drivers, so no dimension is a core dimension:
    `xarray.apply_ufunc` broadcasts the inputs, static or daily, onto one another
    and hands the kernel whole blocks.
    """
    time = sole_time_dim(lai_obs, "lai_obs")
    outputs = xr.apply_ufunc(
        _acm_kernel,
        lai_obs,
        max_temperature,
        min_temperature,
        shortwave_radiation * _W_M2_TO_MJ_M2_D,
        co2,
        days_from_midsummer,
        output_core_dims=[[], []],
        kwargs=settings,
        dask="parallelized",
        keep_attrs=False,
        output_dtypes=[float, float],
    )
    return cast(
        AcmOut,
        {
            name: da.transpose(time, ...)
            for name, da in zip(_ACM_OUTPUT_NAMES, outputs, strict=True)
        },
    )


@check_annotations
@stamp_output_units
def days_from_midsummer(
    latitude: Annotated[DataArray, Unit("degrees")],
    lai_obs: Annotated[DataArray, DAILY],
) -> Annotated[DataArray, Unit("d"), DAILY]:
    """Days from midsummer, the calendar driver of ACM's day-of-year correction.

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
    day_of_year = xr.DataArray(dates.dayofyear, coords={time: dates}, dims=time)
    midsummer = xr.where(latitude >= 0, _MIDSUMMER_NORTH, _MIDSUMMER_SOUTH)
    distance = abs(day_of_year - midsummer)
    distance = np.minimum(distance, 365 - distance)
    result = xr.where(
        abs(latitude) < _TROPIC_LATITUDE, _TROPICAL_DAYS_FROM_MIDSUMMER, distance
    ).astype(float)
    result.attrs.clear()
    return result.transpose(time, ...)


@extract_fields()
@check_annotations
@stamp_output_units
def acm(
    lai_obs: Annotated[DataArray, Unit("1"), DAILY],
    max_temperature: Annotated[DataArray, Unit("degC"), DAILY],
    min_temperature: Annotated[DataArray, Unit("degC"), DAILY],
    shortwave_radiation: Annotated[DataArray, Unit("W m-2"), DAILY],
    co2: Annotated[DataArray, Unit("ppm"), DAILY],
    days_from_midsummer: Annotated[DataArray, Unit("d"), DAILY],
    *,
    acm_foliar_nitrogen: float = 1.92,
    acm_canopy_height: float = 24.0,
    acm_water_potential_difference: float = -2.5,
    acm_nue: float = 2.95,
    acm_nue_temperature_coefficient: float = 0.018,
    acm_co2_compensation_point: float = 32.6,
    acm_co2_half_saturation: float = 576.7,
    acm_conductance_temperature_coefficient: float = -0.029,
    acm_conductance_height_coefficient: float = 0.315,
    acm_max_quantum_yield: float = 0.989,
    acm_quantum_yield_lai_coefficient: float = 0.873,
    acm_day_length_coefficient: float = -0.0018,
    acm_day_length_constant: float = 1.81,
) -> AcmOut:
    """
    Run the Aggregated Canopy Model, version 1 (Williams et al., 1997).

    The calibrated parameters default to Table 2 of the paper, and the site
    settings to Harvard Forest (Table 4).

    Parameters
    ----------
    lai_obs
        Observed leaf area index (square metres of leaf per square metre of
        ground).
    max_temperature
        Daily maximum air temperature (degrees Celsius).
    min_temperature
        Daily minimum air temperature (degrees Celsius).
    shortwave_radiation
        Daily mean downwelling shortwave radiation at the surface (watts per
        square metre).
    co2
        Atmospheric CO2 concentration (parts per million).
    days_from_midsummer
        Days from the summer solstice of the cell's hemisphere (days). Output of
        the `days_from_midsummer` node.

    Other Parameters
    ----------------
    acm_foliar_nitrogen
        Mean foliar nitrogen concentration, N (grams of nitrogen per square
        metre of leaf).
    acm_canopy_height
        Canopy height, H (metres).
    acm_water_potential_difference
        Difference between minimum leaf water potential and soil water
        potential, Psi_d (megapascals). Negative; more negative means wetter
        soil.
    acm_nue
        Nitrogen-use efficiency parameter, a1 (grams of carbon per gram of
        nitrogen per day).
    acm_nue_temperature_coefficient
        Temperature coefficient of nitrogen-use efficiency, a2 (per degree
        Celsius).
    acm_co2_compensation_point
        Canopy CO2 compensation point, theta (micromoles per mole).
    acm_co2_half_saturation
        Canopy CO2 half-saturation point, k (micromoles per mole).
    acm_conductance_temperature_coefficient
        Temperature coefficient of canopy conductance, b1 (per degree Celsius).
    acm_conductance_height_coefficient
        Coefficient of canopy height in canopy conductance, b2 (degrees Celsius
        per metre). Table 2 names it the temperature range constant of canopy
        conductance.
    acm_max_quantum_yield
        Maximum canopy quantum yield, c1 (grams of carbon per megajoule).
    acm_quantum_yield_lai_coefficient
        LAI-canopy quantum yield coefficient, c2 (dimensionless).
    acm_day_length_coefficient
        Day length constant, d1 (per day).
    acm_day_length_constant
        Midsummer coefficient, d2 (dimensionless).

    Returns
    -------
    AcmOut
        Daily GPP and internal CO2 concentration; see `AcmOut`.
    """
    if acm_water_potential_difference >= 0:
        raise ValueError(
            "acm_water_potential_difference must be negative (leaf water potential "
            f"below soil water potential); got {acm_water_potential_difference}."
        )
    return _acm(
        lai_obs,
        max_temperature,
        min_temperature,
        shortwave_radiation,
        co2,
        days_from_midsummer,
        foliar_nitrogen=acm_foliar_nitrogen,
        canopy_height=acm_canopy_height,
        water_potential_difference=acm_water_potential_difference,
        nue=acm_nue,
        nue_temperature_coefficient=acm_nue_temperature_coefficient,
        co2_compensation_point=acm_co2_compensation_point,
        co2_half_saturation=acm_co2_half_saturation,
        conductance_temperature_coefficient=acm_conductance_temperature_coefficient,
        conductance_height_coefficient=acm_conductance_height_coefficient,
        max_quantum_yield=acm_max_quantum_yield,
        quantum_yield_lai_coefficient=acm_quantum_yield_lai_coefficient,
        day_length_coefficient=acm_day_length_coefficient,
        day_length_constant=acm_day_length_constant,
    )
