"""Atmospheric pressure from elevation, for a pipeline with no pressure product.

The P-model's sensitivity to pressure is small next to its sensitivity to light,
temperature and VPD, and day-to-day synoptic variation is a percent or two. A
standard-atmosphere pressure for each pixel's elevation is therefore a common
stand-in where no pressure series is to hand.
"""

from typing import Annotated

import xarray as xr
from pyrealm.core.pressure import calc_patm
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from ..temporal import DAILY


@check_annotations
@stamp_output_units(overwrite=True)
def pressure(
    elevation: Annotated[DataArray, Unit("m")],
    temperature: Annotated[DataArray, Unit("degC"), DAILY],
) -> Annotated[DataArray, Unit("Pa"), DAILY]:
    """Standard-atmosphere pressure at each pixel's elevation, repeated daily.

    pyrealm's `calc_patm`, which assumes a linear temperature lapse with height.
    Its consumers declare a daily pressure, so the per-pixel value is repeated
    along the daily time axis of ``temperature``, which supplies nothing else.

    Parameters
    ----------
    elevation
        Elevation above sea level (metres).
    temperature
        Daily mean air temperature (degrees Celsius), used for its time axis
        only.
    """
    patm = xr.apply_ufunc(calc_patm, elevation, dask="parallelized")
    return patm.broadcast_like(temperature)
