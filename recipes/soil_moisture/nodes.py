"""Nodes that turn COSMOS-UK site data into SPLASH's daily forcing.

COSMOS-UK measures most of what SPLASH needs, under its own names and units. These
nodes fill the gaps: precipitation becomes a gap-free rate, and sunshine fraction,
which COSMOS-UK does not measure, is recovered from incoming shortwave radiation.
``max_soil_moisture`` is a starting value for the calibration in ``demo.py``, which
overrides it on every run.
"""

from typing import Annotated

import numpy as np
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


def _day_of_year(da: xr.DataArray) -> xr.DataArray:
    return da[sole_time_dim(da, "the daily series")].dt.dayofyear


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def extraterrestrial_shortwave_daily(
    latitude: Annotated[xr.DataArray, Unit("degrees")],
    swin: Annotated[xr.DataArray, Unit("MJ m-2 d-1")],
) -> Annotated[xr.DataArray, Unit("MJ m-2 d-1")]:
    """Daily shortwave radiation at the top of the atmosphere.

    FAO-56 (Allen et al., 1998, eqs. 21-25), on the days of ``swin``.
    """
    day = _day_of_year(swin)
    phi = np.deg2rad(latitude)
    declination = 0.409 * np.sin(2 * np.pi / 365 * day - 1.39)
    inverse_distance = 1 + 0.033 * np.cos(2 * np.pi / 365 * day)
    sunset_angle = np.arccos(-np.tan(phi) * np.tan(declination))
    return (
        37.586
        * inverse_distance
        * (
            sunset_angle * np.sin(phi) * np.sin(declination)
            + np.cos(phi) * np.cos(declination) * np.sin(sunset_angle)
        )
    )


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def sunshine_fraction_daily(
    swin: Annotated[xr.DataArray, Unit("MJ m-2 d-1")],
    extraterrestrial_shortwave_daily: Annotated[xr.DataArray, Unit("MJ m-2 d-1")],
    elevation: Annotated[xr.DataArray, Unit("m")],
) -> Annotated[xr.DataArray, Unit("1")]:
    """Sunshine fraction, by inverting SPLASH's transmissivity model.

    SPLASH relates the shortwave radiation reaching the ground to the radiation at
    the top of the atmosphere by ``(0.25 + 0.5 * sf) * (1 + 2.67e-5 * elevation)``.
    Gaps in ``swin`` are filled by linear interpolation first.
    """
    filled = swin.interpolate_na(sole_time_dim(swin, "swin"))
    transmissivity = filled / extraterrestrial_shortwave_daily
    return ((transmissivity / (1 + 2.67e-5 * elevation) - 0.25) / 0.5).clip(0, 1)


@xra.check_annotations
@xra.stamp_output_units(overwrite=True)
def max_soil_moisture(
    elevation: Annotated[xr.DataArray, Unit("m")],
    *,
    initial_max_soil_moisture: float = 150.0,
) -> Annotated[xr.DataArray, Unit("mm")]:
    """A uniform bucket capacity, ``initial_max_soil_moisture`` at every site."""
    return xr.full_like(elevation, initial_max_soil_moisture, dtype=float)
