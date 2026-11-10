"""The bridges between SPLASH, the P-model and SGAM.

None of the three models knows the others exist. Two connect only when a name and
its units line up, and between these three they mostly do not, so each function
here converts one model's output into the next one's input. The docstrings record
why each conversion is what it is. The full-pipeline recipe has the same bridges,
and the ones on to RothC.
"""

from typing import Annotated

import xarray as xr
import xarray_annotated as xra
from catena.io import sole_time_dim
from xarray_annotated import Unit

from viresco.temporal import WEEKLY

# SPLASH to the P-model: water.


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def aridity_index(
    potential_evapotranspiration: Annotated[xr.DataArray, Unit("mm d-1")],
    precipitation: Annotated[xr.DataArray, Unit("mm d-1")],
) -> Annotated[xr.DataArray, Unit("1")]:
    """Climatological aridity, PET over precipitation, one value per pixel.

    pyrealm's aridity index accumulates both terms over the whole record rather
    than giving a time series. SPLASH computes PET on its way to AET and exposes
    it, so the bridge is a sum and a divide.
    """
    time = sole_time_dim(precipitation, "precipitation")
    return potential_evapotranspiration.sum(time) / precipitation.sum(time)


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
