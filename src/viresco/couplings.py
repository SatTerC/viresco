"""Couplings: one model's outputs turned into another model's inputs.

No model knows the others exist. Two connect only where a name and its units
line up, and between viresco's models they mostly do not, so each function here
makes one model's output into a node another consumes. Each is named
``<target>__<source>``, for the node it produces and the registered model it
takes from, and is selected by a key named for its target:

```toml
[couplings]
volumetric_water_content_from = "splash"
```

No coupling has a default, so a key left unset adds no node and the section is
harmless when enabled. A coupling acts at its source's frequency; a coarser
consumer takes means or totals of it by ``[[resample]]``. `viresco setup` writes
the keys wherever a model's input is produced, under another name or in other
units, by another chosen model. See ``docs/adr/0003-component-kinds.md``.
"""

from typing import Annotated

import xarray_annotated as xra
from catena.io import sole_time_dim
from hamilton.function_modifiers import config
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from .temporal import DAILY, MONTHLY, WEEKLY, offset, time_behaviour

# --- SPLASH: water and light --- #


@config.when(volumetric_water_content_from="splash")
@check_annotations
@stamp_output_units(overwrite=True)
def volumetric_water_content__splash(
    soil_moisture: Annotated[DataArray, Unit("mm"), DAILY],
    max_soil_moisture: Annotated[DataArray, Unit("mm")],
    *,
    bucket_porosity: float = 0.45,
) -> Annotated[DataArray, Unit("m3 m-3"), DAILY]:
    """Volumetric water content, from SPLASH's depth of water in a bucket.

    The P-model, as pyrealm's ``theta`` with a ``lavergne20`` optimal chi, and
    SGAM, against each plant type's wilting point and field capacity, want the
    fraction of the soil's volume that is water. SPLASH holds a depth of water in
    a bucket of capacity ``max_soil_moisture``, so their ratio is the relative
    saturation, and multiplying by a porosity makes it a volume fraction.

    Parameters
    ----------
    soil_moisture
        Daily soil water held in SPLASH's bucket (millimetres).
    max_soil_moisture
        The bucket's capacity (millimetres).

    Other Parameters
    ----------------
    bucket_porosity
        Volume fraction of the soil that is pore space, the water content of the
        full bucket. 0.45 is a representative value for a mineral soil.
    """
    return soil_moisture / max_soil_moisture * bucket_porosity


@config.when(aridity_index_from="splash")
@time_behaviour("record")
@check_annotations
@stamp_output_units(overwrite=True)
def aridity_index__splash(
    potential_evapotranspiration: Annotated[DataArray, Unit("mm d-1"), DAILY],
    precipitation: Annotated[DataArray, Unit("mm d-1"), DAILY],
) -> Annotated[DataArray, Unit("1")]:
    """Climatological aridity: potential evapotranspiration over precipitation.

    pyrealm's ``sandoval`` quantum yield takes one aridity index per cell, the
    ratio of the two totals over the whole record. It is PET, not actual
    evapotranspiration, since actual evapotranspiration is what the soil gave
    up, so its ratio to precipitation is near 1 wherever water limits
    evaporation, which is the regime the index exists to detect.

    Parameters
    ----------
    potential_evapotranspiration
        Daily potential evapotranspiration from SPLASH (millimetres per day).
    precipitation
        Daily precipitation (millimetres per day).
    """
    time = sole_time_dim(precipitation, "precipitation")
    return potential_evapotranspiration.sum(time) / precipitation.sum(time)


@config.when(ppfd_from="splash")
@check_annotations
@stamp_output_units(overwrite=True)
def ppfd__splash(
    estimated_ppfd: Annotated[DataArray, Unit("mol m-2 d-1"), DAILY],
) -> Annotated[DataArray, Unit("umol m-2 s-1"), DAILY]:
    """PPFD from SPLASH's daily photon total.

    A unit conversion: the daily total becomes the mean rate over the 24-hour
    day. SPLASH estimates the radiation from sunshine fraction and latitude, so
    this needs no radiation input beyond what SPLASH already takes. The key
    ``ppfd_from = "splash"`` also turns off `viresco.drivers.radiation`'s
    ``ppfd``, so the two may be enabled together.

    Parameters
    ----------
    estimated_ppfd
        Daily total PPFD from SPLASH (moles per square metre per day).
    """
    return xra.units.convert(estimated_ppfd, "umol m-2 s-1")


# --- The P-model: carbon --- #


@config.when(gpp_from="pmodel")
@check_annotations
@stamp_output_units(overwrite=True)
def gpp__pmodel(
    gpp_flux: Annotated[DataArray, Unit("ug m-2 s-1"), DAILY],
) -> Annotated[DataArray, Unit("g m-2 d-1"), DAILY]:
    """Gross primary productivity as a daily rate, from the P-model's flux.

    pyrealm reports GPP as a mean flux in micrograms of carbon per square metre
    per second; ACM, and SGAM through a weekly mean, use grams per square metre
    per day: 86400 s d-1 times 1e-6 g ug-1.

    Parameters
    ----------
    gpp_flux
        Daily GPP from the P-model (micrograms of carbon per square metre per
        second).
    """
    return xra.units.convert(gpp_flux, "g m-2 d-1")


@config.when(lue_from="pmodel")
@check_annotations
@stamp_output_units(overwrite=True)
def lue__pmodel(
    lue_photon: Annotated[DataArray, Unit("g mol-1"), DAILY],
    *,
    par_photons_per_mj: float = 4.57,
) -> Annotated[DataArray, Unit("g MJ-1"), DAILY]:
    """Light use efficiency per unit energy of absorbed PAR.

    pyrealm defines LUE against PPFD, a photon flux, so its denominator is moles
    of photons; SGAM wants carbon per megajoule of PAR. The factor is the photon
    content of PAR, a property of the light rather than a unit conversion, so it
    is a setting.

    Parameters
    ----------
    lue_photon
        Daily light use efficiency from the P-model (grams of carbon per mole of
        photons).

    Other Parameters
    ----------------
    par_photons_per_mj
        Photon content of PAR (moles per megajoule). 4.57 is the standard value
        for the 400-700 nm band. `viresco.drivers.radiation` uses the same
        constant under the same name, so one setting serves both.
    """
    return lue_photon * par_photons_per_mj


# --- SGAM: litter to soil --- #


@config.when(soil_carbon_input_monthly_from="sgam")
@time_behaviour("record")
@check_annotations
@stamp_output_units
def soil_carbon_input_monthly__sgam(
    litter_pool_weekly: Annotated[DataArray, Unit("g m-2"), WEEKLY],
) -> Annotated[DataArray, Unit("t ha-1"), MONTHLY]:
    """Carbon entering the soil each month: the litter produced that month.

    SGAM's litter pool only accumulates, since decomposition is RothC's job, so
    the monthly litterfall is its increment: the weekly differences, summed
    within each month. The increment, unlike a sum of SGAM's turnover outputs,
    includes litter from disturbance events.

    Parameters
    ----------
    litter_pool_weekly
        SGAM's accumulated litter pool (grams of carbon per square metre).
    """
    time = sole_time_dim(litter_pool_weekly, "litter_pool_weekly")
    litterfall = litter_pool_weekly.diff(time).resample({time: offset("monthly")})
    return xra.units.convert(litterfall.sum(keep_attrs=True), "t ha-1")
