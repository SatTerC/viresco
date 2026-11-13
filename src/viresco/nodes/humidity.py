"""Vapour pressure deficit from the humidity variable a dataset provides.

Climate datasets rarely distribute VPD. They give temperature and one measure of
humidity: dewpoint temperature (ERA5, ERA5-Land), specific humidity (CHESS-met)
or relative humidity (HadUK-Grid, station data). This module derives ``vpd``, in
the pascals the P-model and SGAM take, from whichever one a pipeline has.

The config key ``vpd_from`` chooses the variant: ``"dewpoint"`` (the default,
used when the key is unset), ``"specific_humidity"`` or ``"relative_humidity"``.
Saturation vapour pressure is pyrealm's Magnus equation
(`pyrealm.core.hygro.calc_vp_sat`), the one its own conversions use.

Daily VPD computed from daily mean temperature and humidity understates the
daytime deficit, because saturation vapour pressure is convex in temperature.
A daily mean is still what the P-model's other daily drivers are. Where daily
mean humidity is wetter than saturation at daily mean temperature, the deficit
is clipped at zero rather than left negative.
"""

from collections.abc import Callable
from typing import Annotated

import numpy as np
import xarray as xr
from hamilton.function_modifiers import config
from numpy.typing import NDArray
from pyrealm.core.hygro import (
    calc_vp_sat,
    convert_rh_to_vpd,
    convert_sh_to_vpd,
    convert_vp_to_vpd,
)
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from ..temporal import DAILY

#: The non-default ``vpd_from`` values; any other value, or none, is dewpoint.
_OTHER_SOURCES = ["specific_humidity", "relative_humidity"]

#: pyrealm's hygrometric functions work in kilopascals.
_PA_PER_KPA = 1000.0


def _deficit(conversion: Callable[..., object], *args: DataArray) -> DataArray:
    """Apply a pyrealm conversion to kPa, then return Pa with no negative deficit.

    Through `xarray.apply_ufunc`, because pyrealm's functions take and return
    numpy arrays; they are element-wise, so no core dimensions are declared.
    """
    vpd_kpa = xr.apply_ufunc(conversion, *args, dask="parallelized")
    return (vpd_kpa * _PA_PER_KPA).clip(min=0.0)


def _vp_to_vpd_from_dewpoint(
    dewpoint: NDArray[np.float64], temperature: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Deficit in kPa, with the vapour pressure saturated at the dewpoint."""
    return convert_vp_to_vpd(calc_vp_sat(dewpoint), temperature)


@config.when_not_in(vpd_from=_OTHER_SOURCES)
@check_annotations
@stamp_output_units(overwrite=True)
def vpd__dewpoint(
    temperature: Annotated[DataArray, Unit("degC"), DAILY],
    dewpoint_temperature: Annotated[DataArray, Unit("degC"), DAILY],
) -> Annotated[DataArray, Unit("Pa"), DAILY]:
    """Vapour pressure deficit from dewpoint temperature.

    The actual vapour pressure is the saturation vapour pressure at the dewpoint,
    so the deficit is saturation at the air temperature less saturation at the
    dewpoint.

    Parameters
    ----------
    temperature
        Daily mean air temperature (degrees Celsius).
    dewpoint_temperature
        Daily mean dewpoint temperature (degrees Celsius). ERA5 distributes
        this in kelvin, as ``d2m``: convert it before it reaches this node.
    """
    return _deficit(_vp_to_vpd_from_dewpoint, dewpoint_temperature, temperature)


@config.when(vpd_from="specific_humidity")
@check_annotations
@stamp_output_units(overwrite=True)
def vpd__specific_humidity(
    temperature: Annotated[DataArray, Unit("degC"), DAILY],
    specific_humidity: Annotated[DataArray, Unit("kg kg-1"), DAILY],
    pressure: Annotated[DataArray, Unit("Pa"), DAILY],
) -> Annotated[DataArray, Unit("Pa"), DAILY]:
    """Vapour pressure deficit from specific humidity and air pressure.

    Parameters
    ----------
    temperature
        Daily mean air temperature (degrees Celsius).
    specific_humidity
        Daily mean specific humidity: mass of water vapour per mass of moist air
        (kilograms per kilogram).
    pressure
        Daily mean atmospheric pressure (pascals). `viresco.nodes.pressure`
        derives one from elevation where no pressure product is to hand.
    """
    return _deficit(
        convert_sh_to_vpd, specific_humidity, temperature, pressure / _PA_PER_KPA
    )


@config.when(vpd_from="relative_humidity")
@check_annotations
@stamp_output_units(overwrite=True)
def vpd__relative_humidity(
    temperature: Annotated[DataArray, Unit("degC"), DAILY],
    relative_humidity: Annotated[DataArray, Unit("1"), DAILY],
) -> Annotated[DataArray, Unit("Pa"), DAILY]:
    """Vapour pressure deficit from relative humidity.

    Parameters
    ----------
    temperature
        Daily mean air temperature (degrees Celsius).
    relative_humidity
        Daily mean relative humidity, as a fraction (0-1), not a percentage.
        pyrealm warns on values above 1.
    """
    return _deficit(convert_rh_to_vpd, relative_humidity, temperature)
