"""Dimension names, read off the data rather than assumed.

A model works on arrays with one time dimension and at most one other, the spatial
dimension. Neither name is fixed: catena's gridded layer stacks ``(y, x)`` into
``pixel``, a station file has ``site``, and both work as they come. The time
dimension is the one whose coordinate is datetime-like (`catena.io.sole_time_dim`);
the spatial dimension is whatever else there is (`space_dim`).
"""

import xarray as xr
from catena.io import time_dims


def space_dim(**arrays: xr.DataArray | xr.Dataset) -> str:
    """Return the one spatial dimension that ``arrays`` share.

    Each keyword names an input in the error raised when there is no such
    dimension. An array may have no spatial dimension, as a scalar parameter does,
    but no array may have more than one, and those that have one must agree.

    Raises
    ------
    ValueError
        If an array has more than one non-time dimension, if two arrays disagree
        on the spatial dimension's name, or if none of them has one.
    """
    found: dict[str, list[str]] = {}
    for name, obj in arrays.items():
        temporal = set(time_dims(obj))
        others = [str(dim) for dim in obj.dims if dim not in temporal]
        if len(others) > 1:
            raise ValueError(
                f"{name} has non-time dimensions {others}, but models take at most "
                "one spatial dimension. Stack them into one, e.g. with "
                f"`.stack(pixel={tuple(others)})`."
            )
        if others:
            found.setdefault(others[0], []).append(name)
    if len(found) == 1:
        return next(iter(found))
    if not found:
        raise ValueError(
            f"None of {', '.join(arrays)} has a spatial dimension; models need "
            "one, even if it has length 1."
        )
    detail = "; ".join(f"{dim!r} on {', '.join(names)}" for dim, names in found.items())
    raise ValueError(
        f"Inputs disagree on the spatial dimension: {detail}. Rename them to one name."
    )
