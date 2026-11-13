"""Daily series from coarser or irregular ones, by linear interpolation in time.

Two P-model drivers are not distributed daily. fAPAR comes as 4-, 8- or 10-day
composites (MODIS MCD15A3H and MCD15A2H, VIIRS, Copernicus Global Land), with
gaps where cloud defeated the retrieval. CO2 comes as a monthly or annual
record, often one global series with no spatial axis. These nodes put both onto
the pipeline's daily time axis, taken from ``temperature``.

Each series is interpolated linearly in time through its valid values, so a gap
is bridged by the values either side of it. Days before the first valid value
or after the last take that value: nothing is extrapolated. A pixel with no
valid value at all stays NaN. A series with no spatial axis is repeated to every
pixel.

Upsampling like this is not specific to carbon. If catena gains it, these nodes
go.
"""

from typing import Annotated

import numpy as np
import xarray as xr
from catena.io import sole_time_dim
from numpy.typing import NDArray
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from ..temporal import DAILY


def _interp_series(
    values: NDArray[np.float64],
    source: NDArray[np.float64],
    target: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Interpolate one series onto ``target`` through its finite values only."""
    valid = np.isfinite(values)
    if not valid.any():
        return np.full(target.shape, np.nan)
    # `np.interp` holds the end values beyond the source's range: no extrapolation.
    return np.interp(target, source[valid], values[valid])


def _to_daily(coarse: DataArray, template: DataArray, what: str) -> DataArray:
    """Interpolate ``coarse`` onto ``template``'s time axis and spatial shape."""
    source_dim = sole_time_dim(coarse, what)
    target_dim = sole_time_dim(template, "temperature")
    # Times as float nanoseconds, the axis `np.interp` interpolates along.
    source = coarse[source_dim].values.astype("datetime64[ns]").astype(np.float64)
    target = template[target_dim].values.astype("datetime64[ns]").astype(np.float64)
    daily = xr.apply_ufunc(
        _interp_series,
        coarse.astype(np.float64),
        input_core_dims=[[source_dim]],
        output_core_dims=[[target_dim]],
        exclude_dims={source_dim},
        kwargs={"source": source, "target": target},
        vectorize=True,
        dask="parallelized",
        output_dtypes=[np.float64],
        dask_gufunc_kwargs={"output_sizes": {target_dim: target.size}},
    )
    daily = daily.assign_coords({target_dim: template[target_dim]})
    return daily.broadcast_like(template).transpose(*template.dims)


@check_annotations
@stamp_output_units(overwrite=True)
def fapar(
    fapar_coarse: Annotated[DataArray, Unit("1")],
    temperature: Annotated[DataArray, Unit("degC"), DAILY],
) -> Annotated[DataArray, Unit("1"), DAILY]:
    """Daily fAPAR from composites at a coarser or irregular step.

    Clipped to 0-1 afterwards, since a retrieval can stray just outside it and
    pyrealm rejects fAPAR beyond that range. Mask cloud-flagged or low-quality
    retrievals to NaN beforehand, and they are bridged like any other gap.

    Parameters
    ----------
    fapar_coarse
        Fraction of absorbed photosynthetically active radiation (0-1), at the
        composite dates the product gives. It declares no frequency, so a
        composite period of any length, or an irregular one, is accepted.
    temperature
        Daily mean air temperature (degrees Celsius), used for its time axis
        and spatial shape only.
    """
    return _to_daily(fapar_coarse, temperature, "fapar_coarse").clip(0.0, 1.0)


@check_annotations
@stamp_output_units(overwrite=True)
def co2(
    co2_coarse: Annotated[DataArray, Unit("ppm")],
    temperature: Annotated[DataArray, Unit("degC"), DAILY],
) -> Annotated[DataArray, Unit("ppm"), DAILY]:
    """Daily atmospheric CO2 from a monthly or annual record.

    Parameters
    ----------
    co2_coarse
        Atmospheric CO2 concentration (parts per million) at the record's
        dates, such as NOAA's Mauna Loa monthly means. It declares no frequency,
        and may have no spatial axis, in which case every pixel gets the same
        series.
    temperature
        Daily mean air temperature (degrees Celsius), used for its time axis
        and spatial shape only.
    """
    return _to_daily(co2_coarse, temperature, "co2_coarse")
