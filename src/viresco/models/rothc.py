"""RothC soil carbon model interface for the Viresco pipeline."""

from typing import Annotated, TypedDict, cast

import numpy as np
import pandas as pd
import xarray as xr
from catena.io import sole_time_dim
from hamilton.function_modifiers import config, extract_fields
from numpy.typing import NDArray
from rothc_py import RothC, RothCParams, percent_modern_c
from rothc_py.containers import InputData
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from ..temporal import MONTHLY, time_behaviour, time_index

#: The process this model represents; see `viresco.registry.DOMAINS`.
DOMAIN = "soil carbon"


class RothCOut(TypedDict):
    """Outputs of the `rothc` node, at monthly resolution.

    All quantities are carbon mass per unit ground area (tonnes of carbon per
    hectare): the first four are the active soil-carbon pools, the fifth is their
    total, and the last is the month's respiration flux.
    """

    decomposable_plant_material_monthly: Annotated[DataArray, Unit("t ha-1"), MONTHLY]
    """Decomposable plant material (DPM) pool (tonnes of carbon per hectare)."""
    resistant_plant_material_monthly: Annotated[DataArray, Unit("t ha-1"), MONTHLY]
    """Resistant plant material (RPM) pool (tonnes of carbon per hectare)."""
    microbial_biomass_monthly: Annotated[DataArray, Unit("t ha-1"), MONTHLY]
    """Microbial biomass (BIO) pool (tonnes of carbon per hectare)."""
    humified_organic_matter_monthly: Annotated[DataArray, Unit("t ha-1"), MONTHLY]
    """Humified organic matter (HUM) pool (tonnes of carbon per hectare)."""
    soil_organic_carbon_monthly: Annotated[DataArray, Unit("t ha-1"), MONTHLY]
    """Total soil organic carbon: the sum of the DPM, RPM, BIO, HUM and inert
    organic matter pools (tonnes of carbon per hectare)."""
    heterotrophic_respiration_monthly: Annotated[DataArray, Unit("t ha-1"), MONTHLY]
    """Carbon released as CO2 by microbial decomposition during the month
    (tonnes of carbon per hectare)."""


# RothC output keys, in the order they are returned by `_rothc_1px` and mapped
# onto the DAG node names below.
_ROTHC_OUTPUT_KEYS: tuple[str, ...] = (
    "DPM_t_C_ha",
    "RPM_t_C_ha",
    "BIO_t_C_ha",
    "HUM_t_C_ha",
    "SOC_t_C_ha",
    "CO2_t_C_ha",
)

#: `RothCOut` fields, matching `_ROTHC_OUTPUT_KEYS` position by position. The
#: units are declared on `RothCOut` and stamped by `rothc`.
_ROTHC_OUTPUT_NAMES: tuple[str, ...] = (
    "decomposable_plant_material_monthly",
    "resistant_plant_material_monthly",
    "microbial_biomass_monthly",
    "humified_organic_matter_monthly",
    "soil_organic_carbon_monthly",
    "heterotrophic_respiration_monthly",
)


def _rothc_1px(
    temperature: NDArray[np.float64],
    precipitation: NDArray[np.float64],
    potential_evapotranspiration: NDArray[np.float64],
    plant_cover: NDArray[np.bool_],
    dpm_rpm_ratio: NDArray[np.float64],
    soil_carbon_input: NDArray[np.float64],
    farmyard_manure_input: NDArray[np.float64],
    clay: float,
    depth: float,
    iom: float,
    *,
    t_mod: list[float],
    n_spinup_months: int,
    dpm_rate: float,
    rpm_rate: float,
    bio_rate: float,
    hum_rate: float,
    evap_factor: float,
    equilibrium_threshold: float,
    zero_threshold: float,
) -> tuple[NDArray[np.float64], ...]:
    """Run RothC for a single cell.

    The climate/driver arguments are 1D ``(time,)`` arrays for one cell; ``clay``,
    ``depth`` and ``iom`` are per-cell scalars. ``t_mod`` (the percent-modern-carbon
    series) depends only on the date range, so it is computed once in `_rothc`
    and passed through unchanged. Returns one ``(time,)`` array per output pool/flux,
    ordered as `_ROTHC_OUTPUT_KEYS`. This is the per-cell kernel mapped over the
    spatial dimension by `_rothc` via `xarray.apply_ufunc`.
    """
    params = RothCParams(
        clay=float(clay),
        depth=float(depth),
        iom=float(iom),
        dpm_rate=dpm_rate,
        rpm_rate=rpm_rate,
        bio_rate=bio_rate,
        hum_rate=hum_rate,
        evap_factor=evap_factor,
        equilibrium_threshold=equilibrium_threshold,
        zero_threshold=zero_threshold,
    )
    model = RothC(params)
    # rothc_py's ``t_evap`` slot is nominally open-pan evaporation, which it scales
    # by ``evap_factor`` to get evapotranspiration. We supply potential
    # evapotranspiration directly (SPLASH computes it via Priestley-Taylor), so
    # ``evap_factor`` defaults to 1.0 here and no conversion is applied.
    data: InputData = {
        "t_tmp": temperature.tolist(),
        "t_rain": precipitation.tolist(),
        "t_evap": potential_evapotranspiration.tolist(),
        "t_PC": plant_cover.astype(int).tolist(),
        "t_DPM_RPM": dpm_rpm_ratio.tolist(),
        "t_C_Inp": soil_carbon_input.tolist(),
        "t_FYM_Inp": farmyard_manure_input.tolist(),
        "t_mod": t_mod,
    }
    spinup_data: InputData = {
        "t_tmp": data["t_tmp"][:n_spinup_months],
        "t_rain": data["t_rain"][:n_spinup_months],
        "t_evap": data["t_evap"][:n_spinup_months],
        "t_PC": data["t_PC"][:n_spinup_months],
        "t_DPM_RPM": data["t_DPM_RPM"][:n_spinup_months],
        "t_C_Inp": data["t_C_Inp"][:n_spinup_months],
        "t_FYM_Inp": data["t_FYM_Inp"][:n_spinup_months],
        "t_mod": data["t_mod"][:n_spinup_months],
    }

    _, outputs = model(data, spinup_data)
    return tuple(np.asarray(outputs[key], dtype=float) for key in _ROTHC_OUTPUT_KEYS)


def _rothc(
    temperature_monthly: DataArray,
    precipitation_monthly: DataArray,
    potential_evapotranspiration_monthly: DataArray,
    plant_cover_monthly: DataArray,
    dpm_rpm_ratio_monthly: DataArray,
    soil_carbon_input_monthly: DataArray,
    farmyard_manure_input_monthly: DataArray,
    clay_content: DataArray,
    soil_depth: DataArray,
    inert_organic_matter: DataArray,
    dates_monthly: pd.Index,
    *,
    rothc_spinup_years: int,
    dpm_rate: float = 10.0,
    rpm_rate: float = 0.3,
    bio_rate: float = 0.66,
    hum_rate: float = 0.02,
    evap_factor: float = 1.0,
    equilibrium_threshold: float = 1e-6,
    zero_threshold: float = 1e-8,
) -> RothCOut:
    """Map `_rothc_1px` over every cell.

    The per-cell RothC kernel is applied via `xarray.apply_ufunc` with time as the
    input/output core dimension and every other dimension broadcast (mapped). The
    climate/driver inputs declare time as their core dim; the static soil inputs
    declare no core dim (so each call receives a per-cell scalar). ``t_mod`` and
    the rate constants are cell-invariant constants passed through ``kwargs``.
    ``dask="parallelized"`` is a no-op for eager numpy inputs but keeps the node
    compatible with a future dask-backed (chunked over space) execution strategy.
    """
    time = sole_time_dim(temperature_monthly, "temperature_monthly")
    n_months = temperature_monthly.sizes[time]

    # NOTE: need to pass a datetime.datetime object (not a numpy.datetime64)
    # DatetimeIndex.to_pydatetime() exists at runtime but is missing from
    # the pandas type stubs, hence the type: ignore.
    start_date = dates_monthly.to_pydatetime()[0]  # type: ignore[reportAttributeAccessIssue]

    # t_mod depends only on the date range, so compute it once and share across cells.
    t_mod = percent_modern_c(start_date=start_date, n_months=n_months)

    outputs = xr.apply_ufunc(
        _rothc_1px,
        temperature_monthly,
        precipitation_monthly,
        potential_evapotranspiration_monthly,
        plant_cover_monthly,
        dpm_rpm_ratio_monthly,
        soil_carbon_input_monthly,
        farmyard_manure_input_monthly,
        clay_content,
        soil_depth,
        inert_organic_matter,
        input_core_dims=[[time]] * 7 + [[]] * 3,
        output_core_dims=[[time]] * 6,
        kwargs={
            "t_mod": t_mod,
            "n_spinup_months": rothc_spinup_years * 12,
            "dpm_rate": dpm_rate,
            "rpm_rate": rpm_rate,
            "bio_rate": bio_rate,
            "hum_rate": hum_rate,
            "evap_factor": evap_factor,
            "equilibrium_threshold": equilibrium_threshold,
            "zero_threshold": zero_threshold,
        },
        vectorize=True,
        dask="parallelized",
        keep_attrs=False,
        output_dtypes=[float] * 6,
    )

    # apply_ufunc drops the time coordinate (a core dim) and puts time last;
    # reattach the coordinate and put time first.
    time_coord = temperature_monthly.coords[time]
    return cast(
        RothCOut,
        {
            name: da.assign_coords({time: time_coord}).transpose(time, ...)
            for name, da in zip(_ROTHC_OUTPUT_NAMES, outputs, strict=True)
        },
    )


@extract_fields()
@time_behaviour("stateful")
@check_annotations
@stamp_output_units
def rothc(
    temperature_monthly: Annotated[DataArray, Unit("degC"), MONTHLY],
    precipitation_monthly: Annotated[DataArray, Unit("mm"), MONTHLY],
    potential_evapotranspiration_monthly: Annotated[DataArray, Unit("mm"), MONTHLY],
    plant_cover_monthly: Annotated[DataArray, MONTHLY],
    dpm_rpm_ratio_monthly: Annotated[DataArray, Unit("1"), MONTHLY],
    soil_carbon_input_monthly: Annotated[DataArray, Unit("t ha-1"), MONTHLY],
    farmyard_manure_input_monthly: Annotated[DataArray, Unit("t ha-1"), MONTHLY],
    clay_content: Annotated[DataArray, Unit("percent")],
    inert_organic_matter: Annotated[DataArray, Unit("t ha-1")],
    soil_depth: Annotated[DataArray, Unit("cm")],
    *,
    rothc_spinup_years: int = 1,
    dpm_rate: float = 10.0,
    rpm_rate: float = 0.3,
    bio_rate: float = 0.66,
    hum_rate: float = 0.02,
    evap_factor: float = 1.0,
    equilibrium_threshold: float = 1e-6,
    zero_threshold: float = 1e-8,
) -> RothCOut:
    """
    Rothamsted Carbon model.

    Monthly resolution input data.

    Parameters
    ----------
    temperature_monthly
        Monthly mean air temperature (degrees Celsius).
    precipitation_monthly
        Monthly total precipitation (millimetres).
    potential_evapotranspiration_monthly
        Monthly total potential evapotranspiration (millimetres).
    plant_cover_monthly
        Monthly plant cover as boolean (True = soil covered by vegetation).
    dpm_rpm_ratio_monthly
        Ratio of decomposable to resistant plant material (dimensionless).
    soil_carbon_input_monthly
        Carbon input amount for the month (tonnes of carbon per hectare).
    farmyard_manure_input_monthly
        Farmyard manure carbon input amount for the month (tonnes of carbon per
        hectare).
    clay_content
        Soil clay content (percent).
    soil_depth
        Soil depth (centimetres).
    inert_organic_matter
        Inert organic matter (tonnes of carbon per hectare).

    Other Parameters
    ----------------
    rothc_spinup_years
        Number of years of climate data used for model spin-up.
    dpm_rate
        Decomposition rate constant for decomposable plant material (per year).
    rpm_rate
        Decomposition rate constant for resistant plant material (per year).
    bio_rate
        Decomposition rate constant for microbial biomass (per year).
    hum_rate
        Decomposition rate constant for humified organic matter (per year).
    evap_factor
        Factor applied to `potential_evapotranspiration_monthly` before RothC's
        water balance (dimensionless). RothC's own driver is open-pan
        evaporation, and rothc_py's 0.75 converts that to evapotranspiration;
        viresco supplies evapotranspiration already, so the default here is 1.0
        (no conversion). Only change it if you are feeding open-pan evaporation
        into this node instead.
    equilibrium_threshold
        Spin-up convergence criterion: maximum annual change in total organic
        carbon (tonnes of carbon per hectare).
    zero_threshold
        Minimum pool size for numerical stability in radiocarbon age
        calculations (tonnes of carbon per hectare).

    Returns
    -------
    RothCOut
        Dictionary of monthly outputs (all in tonnes of carbon per hectare):

        - decomposable_plant_material_monthly: DPM pool
        - resistant_plant_material_monthly: RPM pool
        - microbial_biomass_monthly: microbial biomass (BIO) pool
        - humified_organic_matter_monthly: HUM pool
        - soil_organic_carbon_monthly: total soil organic carbon (sum of pools)
        - heterotrophic_respiration_monthly: CO2 from microbial decomposition

        See `RothCOut` for per-output detail.
    """
    return _rothc(
        temperature_monthly=temperature_monthly,
        precipitation_monthly=precipitation_monthly,
        potential_evapotranspiration_monthly=potential_evapotranspiration_monthly,
        plant_cover_monthly=plant_cover_monthly,
        dpm_rpm_ratio_monthly=dpm_rpm_ratio_monthly,
        soil_carbon_input_monthly=soil_carbon_input_monthly,
        farmyard_manure_input_monthly=farmyard_manure_input_monthly,
        clay_content=clay_content,
        soil_depth=soil_depth,
        inert_organic_matter=inert_organic_matter,
        dates_monthly=time_index(temperature_monthly, "temperature_monthly"),
        rothc_spinup_years=rothc_spinup_years,
        dpm_rate=dpm_rate,
        rpm_rate=rpm_rate,
        bio_rate=bio_rate,
        hum_rate=hum_rate,
        evap_factor=evap_factor,
        equilibrium_threshold=equilibrium_threshold,
        zero_threshold=zero_threshold,
    )


# --- Input-building nodes, needed for RothC --- #
# Each of these produces a monthly series out of per-cell static data, so it needs
# a monthly calendar to build that series against. The time axis lives on the data,
# so each takes ``temperature_monthly`` purely for its time coordinate.


@check_annotations
def plant_cover_monthly(
    plant_type: DataArray,
    latitude: DataArray,
    temperature_monthly: Annotated[DataArray, MONTHLY],
) -> Annotated[DataArray, MONTHLY]:
    """Return monthly plant cover as a boolean mask, accounting for crop seasonality.

    Tree (0), grass (1), and shrub (2) are always considered to cover the soil.
    Crops (3) have a bare season that depends on hemisphere:
      - Northern hemisphere (lat >= 0): bare Nov-Feb
      - Southern hemisphere (lat < 0): bare May-Aug

    Parameters
    ----------
    plant_type
        Plant functional type as an integer (0=tree, 1=grass, 2=shrub, 3=crop),
        one per cell.
    latitude
        Latitude of each cell, on any of ``plant_type``'s dimensions.
    temperature_monthly
        Read only for its monthly time coordinate, which sets the returned
        series' calendar.

    Returns
    -------
    DataArray
        Boolean plant cover, on ``time`` then the inputs' other dimensions.
    """
    time = sole_time_dim(temperature_monthly, "temperature_monthly")
    dates_monthly = time_index(temperature_monthly, "temperature_monthly")
    months = xr.DataArray(dates_monthly.month, coords={time: dates_monthly}, dims=time)
    bare = xr.where(
        latitude >= 0, months.isin([11, 12, 1, 2]), months.isin([5, 6, 7, 8])
    )
    return (~((plant_type == 3) & bare)).transpose(time, ...)


@check_annotations
@stamp_output_units
def dpm_rpm_ratio_monthly(
    plant_type: DataArray,
    temperature_monthly: Annotated[DataArray, MONTHLY],
    *,
    dpm_rpm_ratio_tree: float = 0.25,
    dpm_rpm_ratio_grass: float = 1.44,
    dpm_rpm_ratio_shrub: float = 0.67,
    dpm_rpm_ratio_crop: float = 1.44,
) -> Annotated[DataArray, Unit("1"), MONTHLY]:
    """Return the DPM/RPM ratio for RothC based on plant type.

    The default ratios are the ones given in the RothC documentation.

    Parameters
    ----------
    plant_type
        Plant functional type as an integer (0=tree, 1=grass, 2=shrub, 3=crop),
        one per cell.
    temperature_monthly
        Read only for its monthly time coordinate, which sets the returned
        series' calendar.

    Other Parameters
    ----------------
    dpm_rpm_ratio_tree
        DPM/RPM ratio for tree/woodland (dimensionless).
    dpm_rpm_ratio_grass
        DPM/RPM ratio for improved grassland (dimensionless).
    dpm_rpm_ratio_shrub
        DPM/RPM ratio for shrub/scrub (dimensionless).
    dpm_rpm_ratio_crop
        DPM/RPM ratio for crop (dimensionless).

    Returns
    -------
    DataArray
        DPM/RPM ratio, on ``time`` then ``plant_type``'s dimensions.
    """
    ratio_map = {
        0: dpm_rpm_ratio_tree,
        1: dpm_rpm_ratio_grass,
        2: dpm_rpm_ratio_shrub,
        3: dpm_rpm_ratio_crop,
    }
    time = sole_time_dim(temperature_monthly, "temperature_monthly")
    dates_monthly = time_index(temperature_monthly, "temperature_monthly")
    values = [ratio_map[int(t)] for t in plant_type.values.ravel()]
    ratio = plant_type.copy(data=np.reshape(values, plant_type.shape))
    # Built on ``plant_type`` only for its dims and coords, so drop its attrs for
    # the stamp to fill.
    ratio.attrs.clear()
    return ratio.expand_dims({time: dates_monthly}).copy()


@check_annotations
@stamp_output_units
def farmyard_manure_input_monthly(
    plant_type: DataArray,
    temperature_monthly: Annotated[DataArray, MONTHLY],
) -> Annotated[DataArray, Unit("t ha-1"), MONTHLY]:
    """Return a zero-filled monthly farmyard manure carbon input.

    Parameters
    ----------
    plant_type
        Plant functional type as an integer (0=tree, 1=grass, 2=shrub, 3=crop).
        Used only for its dimensions and coordinates.
    temperature_monthly
        Read only for its monthly time coordinate, which sets the returned
        series' calendar.

    Returns
    -------
    DataArray
        Monthly farmyard manure carbon input, all zeros, on ``time`` then
        ``plant_type``'s dimensions (tonnes of carbon per hectare).
    """
    time = sole_time_dim(temperature_monthly, "temperature_monthly")
    dates_monthly = time_index(temperature_monthly, "temperature_monthly")
    # Built from ``plant_type`` only for its shape/coords, so drop its inherited
    # attrs (``plant_type``'s "dimensionless") for the stamp to fill.
    zeros = xr.zeros_like(plant_type.expand_dims({time: dates_monthly}), dtype=float)
    zeros.attrs.clear()
    return zeros


@config.when(inert_organic_matter_from="falloon")
@check_annotations
@stamp_output_units(overwrite=True)
def inert_organic_matter__falloon(
    organic_carbon_stocks: Annotated[DataArray, Unit("t ha-1")],
) -> Annotated[DataArray, Unit("t ha-1")]:
    """Inert organic matter from total soil organic carbon, after Falloon et al.

    For ``inert_organic_matter_from = "falloon"``; with the key unset,
    ``inert_organic_matter`` is read as data. RothC's inert pool is rarely
    measured, and Falloon et al. (1998) fitted it to total soil organic carbon
    as ``IOM = 0.049 SOC^1.139``, both in tonnes of carbon per hectare.

    Parameters
    ----------
    organic_carbon_stocks
        Total soil organic carbon over RothC's soil depth (tonnes of carbon per
        hectare).
    """
    return 0.049 * organic_carbon_stocks**1.139
