"""Nodes that turn COSMOS-UK site data into SPLASH's daily forcing.

COSMOS-UK measures most of what SPLASH needs, under its own names and units. These
nodes fill the gaps: precipitation becomes a gap-free rate, temperature and
shortwave radiation are interpolated across missing days, and shortwave radiation
is restated in joules, from which SPLASH recovers the sunshine fraction COSMOS-UK
does not measure.
``max_soil_moisture`` is a starting value for the calibration in ``demo.py``, which
overrides it on every run.
"""

from typing import Annotated

import xarray as xr
import xarray_annotated as xra
from catena.io import sole_time_dim
from xarray_annotated import Unit


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def precipitation_daily(
    precip: Annotated[xr.DataArray, Unit("mm")],
) -> Annotated[xr.DataArray, Unit("mm d-1")]:
    """Restate daily precipitation totals as a rate, filling gaps with zero.

    SPLASH carries soil moisture over from one day to the next, so it refuses any
    gap in its forcing.
    """
    return precip.fillna(0)


@xra.check_annotations
def temperature_daily(
    ta: Annotated[xr.DataArray, Unit("degC")],
) -> Annotated[xr.DataArray, Unit("degC")]:
    """Daily mean air temperature, filling gaps by linear interpolation."""
    return ta.interpolate_na(sole_time_dim(ta, "ta"))


@xra.check_annotations
def shortwave_radiation_daily(
    swin: Annotated[xr.DataArray, Unit("MJ m-2 d-1")],
) -> Annotated[xr.DataArray, Unit("J m-2 d-1")]:
    """Incoming shortwave radiation in joules, filling gaps by linear interpolation.

    SPLASH recovers its sunshine fraction from this, with
    ``sunshine_fraction_method = "shortwave"``.
    """
    filled = swin.interpolate_na(sole_time_dim(swin, "swin"))
    return xra.units.convert(filled, "J m-2 d-1")


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def max_soil_moisture(
    *,
    initial_max_soil_moisture: float = 150.0,
) -> Annotated[xr.DataArray, Unit("mm")]:
    """A uniform bucket capacity: one value, which SPLASH applies to every site."""
    return xr.DataArray(initial_max_soil_moisture)
