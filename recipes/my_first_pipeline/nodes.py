"""Nodes that turn COSMOS-UK's daily data into SPLASH's inputs.

COSMOS-UK measures most of what SPLASH needs, under its own names and units, and
with the odd missing day. SPLASH carries soil moisture over from one day to the
next, so it refuses any gap in its forcing. Each node here takes one COSMOS-UK
variable and returns the SPLASH input made from it, gap-free and in the unit
SPLASH declares.
"""

from typing import Annotated

import xarray as xr
import xarray_annotated as xra
from catena.io import sole_time_dim
from xarray_annotated import Unit


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def precipitation(
    precip: Annotated[xr.DataArray, Unit("mm")],
) -> Annotated[xr.DataArray, Unit("mm d-1")]:
    """Restate daily precipitation totals as a rate, filling gaps with zero."""
    return precip.fillna(0)


@xra.check_annotations
def temperature(
    ta: Annotated[xr.DataArray, Unit("degC")],
) -> Annotated[xr.DataArray, Unit("degC")]:
    """Daily mean air temperature, filling gaps by linear interpolation."""
    return ta.interpolate_na(sole_time_dim(ta, "ta"))


@xra.check_annotations
def shortwave_radiation(
    swin: Annotated[xr.DataArray, Unit("MJ m-2 d-1")],
) -> Annotated[xr.DataArray, Unit("J m-2 d-1")]:
    """Incoming shortwave radiation in joules, filling gaps by linear interpolation."""
    filled = swin.interpolate_na(sole_time_dim(swin, "swin"))
    return xra.units.convert(filled, "J m-2 d-1")


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def max_soil_moisture(
    *,
    bucket_capacity: float = 150.0,
) -> Annotated[xr.DataArray, Unit("mm")]:
    """SPLASH's bucket capacity, the same at every site.

    COSMOS-UK does not measure it, so it is a setting. A single value is enough:
    SPLASH applies it to every site.
    """
    return xr.DataArray(bucket_capacity)
