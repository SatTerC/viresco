"""Chunking for arrays a node builds itself and passes to `xarray.apply_ufunc`."""

import xarray as xr


def chunk_like(da: xr.DataArray, *references: xr.DataArray) -> xr.DataArray:
    """Chunk ``da`` as the first dask-backed array in ``references`` is chunked.

    dask cannot estimate the size of object-dtype data, so an unchunked object
    array handed to `xarray.apply_ufunc` alongside chunked inputs fails to
    auto-rechunk. Chunking it explicitly avoids that. A dimension of ``da`` that
    the reference does not have is left whole. Returns ``da`` unchanged when no
    reference is dask-backed, so eager runs stay numpy.
    """
    reference = next((ref for ref in references if ref.chunks is not None), None)
    if reference is None:
        return da
    chunks = reference.chunksizes
    return da.chunk({dim: chunks.get(dim, -1) for dim in da.dims})
