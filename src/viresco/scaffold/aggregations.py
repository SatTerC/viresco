"""How a variable is aggregated when the generator coarsens it.

catena's ``[[resample]]`` defaults to a mean, which is right for most of what
viresco coarsens: temperatures, fluxes and efficiencies averaged over a week or
a month. This table lists the exceptions, the variables whose consumer wants
another aggregation of the same units. The config generator reads it to give
each exception its own ``[[resample]]`` entry with that ``aggfunc``, and
`recipes/config.toml` writes the same entries by hand.

A rate wanted as a per-period total is not listed here: its units change, so the
generator emits a summing ``[[node]]`` for it instead, decided from the declared
units alone.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Aggregation:
    """One variable coarsened by something other than a mean.

    Attributes
    ----------
    variable : str
        Base name (no frequency suffix) of the node being coarsened.
    aggfunc : str
        The ``aggfunc`` of its ``[[resample]]`` entry: one of catena's
        ``"sum"``, ``"max"``, ``"min"``, ``"first"`` or ``"last"``.
    note : str
        Why the mean is wrong for this variable, for the reader of this table.
    """

    variable: str
    aggfunc: str
    note: str = ""


#: Every variable viresco coarsens by something other than a mean. Adding one
#: means adding a row here, not editing the generator.
AGGREGATIONS: tuple[Aggregation, ...] = (
    Aggregation(
        variable="disturbances",
        aggfunc="max",
        note=(
            "SGAM consumes the weekly maximum of the daily disturbance severity. "
            "A mean dilutes one short event by the quiet days around it, and "
            "SGAM under-responds."
        ),
    ),
)


def aggfunc_for(variable: str) -> str:
    """Return the ``aggfunc`` that coarsens ``variable``, ``"mean"`` by default."""
    for aggregation in AGGREGATIONS:
        if aggregation.variable == variable:
            return aggregation.aggfunc
    return "mean"
