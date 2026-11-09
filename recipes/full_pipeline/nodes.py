"""The bridges between SPLASH, the P-model, SGAM and RothC.

None of the four models knows the others exist. Two connect only when a name and
its units line up, and between these four they mostly do not, so each function
here converts one model's output into the next one's input. The docstrings record
why each conversion is what it is.
"""

from typing import Annotated

import xarray as xr
import xarray_annotated as xra
from catena.io import sole_time_dim
from xarray_annotated import Unit

from viresco.temporal import MONTHLY, WEEKLY, offset

# SPLASH to the P-model: water.


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def aridity_index(
    potential_evapotranspiration_daily: Annotated[xr.DataArray, Unit("mm d-1")],
    precipitation_daily: Annotated[xr.DataArray, Unit("mm d-1")],
) -> Annotated[xr.DataArray, Unit("1")]:
    """Climatological aridity, PET over precipitation, one value per pixel.

    pyrealm's aridity index accumulates both terms over the whole record rather
    than giving a time series. SPLASH computes PET on its way to AET and exposes
    it, so the bridge is a sum and a divide.
    """
    time = sole_time_dim(precipitation_daily, "precipitation_daily")
    return potential_evapotranspiration_daily.sum(time) / precipitation_daily.sum(time)


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def volumetric_water_content_weekly(
    soil_moisture_weekly: Annotated[xr.DataArray, Unit("mm"), WEEKLY],
    max_soil_moisture: Annotated[xr.DataArray, Unit("mm")],
    *,
    porosity: float = 0.45,
) -> Annotated[xr.DataArray, Unit("m3 m-3"), WEEKLY]:
    """Volumetric water content, from SPLASH's depth of water in a bucket.

    Both the P-model, as pyrealm's ``theta``, and SGAM, against the PFT's
    ``wilting_point`` and ``field_capacity``, want a volume fraction. Dividing by
    the bucket's capacity gives relative saturation, and multiplying by a
    representative mineral-soil ``porosity`` turns that into a volume fraction.
    """
    return soil_moisture_weekly / max_soil_moisture * porosity


# The P-model to SGAM: carbon. viresco.models.pmodel reports GPP and LUE in
# pyrealm's own units, and names them so they cannot reach SGAM unconverted.


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def gpp_weekly(
    gpp_flux_weekly: Annotated[xr.DataArray, Unit("ug m-2 s-1"), WEEKLY],
) -> Annotated[xr.DataArray, Unit("g m-2 d-1"), WEEKLY]:
    """Gross primary productivity as a daily rate.

    pyrealm's GPP is an instantaneous flux in ug C m-2 s-1, and SGAM wants g C
    m-2 d-1: 86400 s d-1 times 1e-6 g ug-1.
    """
    return xra.units.convert(gpp_flux_weekly, "g m-2 d-1")


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def lue_weekly(
    lue_photon_weekly: Annotated[xr.DataArray, Unit("g mol-1"), WEEKLY],
    *,
    par_photons_per_mj: float = 4.57,
) -> Annotated[xr.DataArray, Unit("g MJ-1"), WEEKLY]:
    """Light use efficiency per unit energy of absorbed PAR.

    pyrealm defines LUE against PPFD, a photon flux, so its denominator is moles
    of photons. SGAM wants carbon per MJ of PAR, and 4.57 mol MJ-1 is the standard
    photon content of PAR over the 400-700 nm band. The factor is a property of
    the light, not a unit conversion, so it is written out rather than converted.
    """
    return lue_photon_weekly * par_photons_per_mj


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def leaf_area_index_weekly(
    leaf_pool_weekly: Annotated[xr.DataArray, Unit("g m-2"), WEEKLY],
    pft_params: xr.Dataset,
) -> Annotated[xr.DataArray, Unit("m2 m-2"), WEEKLY]:
    """Leaf area index: leaf carbon per ground area over leaf carbon per leaf area."""
    return leaf_pool_weekly / pft_params["leaf_carbon_area"]


# SPLASH and SGAM to RothC: monthly totals and soil carbon input.


def _monthly_total(rate: xr.DataArray, what: str) -> xr.DataArray:
    """Sum a daily rate over each month.

    The daily timestep is one day, so the sum of a rate in mm d-1 is numerically
    the monthly total in mm. The sum keeps the rate's label, which the caller's
    declared unit overwrites.
    """
    return rate.resample({sole_time_dim(rate, what): offset("monthly")}).sum()


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def potential_evapotranspiration_monthly(
    potential_evapotranspiration_daily: Annotated[xr.DataArray, Unit("mm d-1")],
) -> Annotated[xr.DataArray, Unit("mm"), MONTHLY]:
    """Monthly total of SPLASH's potential evapotranspiration.

    PET, not AET: RothC's water balance is rainfall minus evaporative demand. AET
    is already suppressed by the dryness RothC is trying to compute, so feeding it
    in would double-count the limitation and hold the soil too wet.
    """
    return _monthly_total(
        potential_evapotranspiration_daily, "potential_evapotranspiration_daily"
    )


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def precipitation_monthly(
    precipitation_daily: Annotated[xr.DataArray, Unit("mm d-1")],
) -> Annotated[xr.DataArray, Unit("mm"), MONTHLY]:
    """Monthly total precipitation.

    A ``[[resample]]`` would average the rate rather than total it, and would feed
    mm d-1 into RothC's mm input.
    """
    return _monthly_total(precipitation_daily, "precipitation_daily")


@xra.check_annotations
@xra.stamp_output_units
def soil_carbon_input_monthly(
    litter_pool_weekly: Annotated[xr.DataArray, Unit("g m-2"), WEEKLY],
) -> Annotated[xr.DataArray, Unit("t ha-1"), MONTHLY]:
    """Carbon entering the soil each month: the litter produced that month.

    SGAM's ``litter_pool`` only accumulates, since decomposition is RothC's job,
    so the monthly litterfall is its increment: the weekly differences, summed
    within each month. The increment, unlike a sum of the ``turnover_*`` outputs,
    includes litter from disturbance events.
    """
    time = sole_time_dim(litter_pool_weekly, "litter_pool_weekly")
    litterfall = litter_pool_weekly.diff(time).resample({time: offset("monthly")})
    return xra.units.convert(litterfall.sum(keep_attrs=True), "t ha-1")


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def inert_organic_matter(
    organic_carbon_stocks: Annotated[xr.DataArray, Unit("t ha-1")],
) -> Annotated[xr.DataArray, Unit("t ha-1")]:
    """RothC's inert organic matter, by the Falloon et al. (1998) equation."""
    return 0.049 * organic_carbon_stocks**1.139
