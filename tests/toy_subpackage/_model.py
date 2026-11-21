"""The toy model's node, in a submodule of its package."""

from typing import Annotated, TypedDict

from hamilton.function_modifiers import extract_fields
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from viresco.temporal import DAILY


class ToyOut(TypedDict):
    """Outputs of the `toy` node."""

    scaled_precipitation: Annotated[DataArray, Unit("mm d-1"), DAILY]
    """Precipitation multiplied by ``factor``."""


@extract_fields()
@check_annotations
@stamp_output_units
def toy(
    precipitation: Annotated[DataArray, Unit("mm d-1"), DAILY],
    *,
    toy_factor: float = 2.0,
) -> ToyOut:
    """Scale precipitation.

    Parameters
    ----------
    precipitation
        Daily precipitation (millimetres per day).

    Other Parameters
    ----------------
    toy_factor
        Multiplier (dimensionless).
    """
    return {"scaled_precipitation": precipitation * toy_factor}
