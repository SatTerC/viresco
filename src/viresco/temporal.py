"""The temporal resolutions a viresco pipeline speaks in.

catena infers nothing from a node's name: an input's frequency is validated
only where a consumer declares it. These are viresco's declarations, the pandas
offsets behind its node names. Daily is the finest resolution viresco models, and
daily nodes have bare names (``temperature``); coarser ones carry a suffix
(``temperature_weekly``, ``temperature_monthly``). This is a viresco convention,
not a catena one. Static nodes are bare too, so a bare name is daily or static,
and only the declared `Freq`, or the absence of one, tells them apart.

`viresco.models` declares these as `Freq` contracts, `viresco.testing.config_gen`
reads them to sort a generated config's variables and writes them into its
``[[resample]]`` entries, and `viresco.testing.data_gen` resamples synthetic
data onto them.

The offsets are unanchored, so ``Freq("7D")`` constrains the spacing only: a
weekly series is accepted whichever weekday it starts on.
"""

from collections.abc import Callable
from typing import Literal, TypeVar, get_args

import pandas as pd
import xarray as xr
from catena.io import sole_time_dim
from xarray_annotated import Freq

#: Daily: one sample per day.
DAILY = Freq("D")

#: Weekly: seven-day spacing, any weekday.
WEEKLY = Freq("7D")

#: Monthly: one sample per calendar month, month-end convention.
MONTHLY = Freq("1ME")

#: The offset behind each input-section label, keyed by the label catena uses.
BY_LABEL: dict[str, Freq] = {
    "daily": DAILY,
    "weekly": WEEKLY,
    "monthly": MONTHLY,
}


def offset(label: str) -> str:
    """Return the pandas offset alias for an input-section ``label``.

    `Freq` carries the offset for contract declaration; this is the same string
    in the form `catena.transforms.resample` and a ``[[resample]]`` entry want.
    """
    try:
        return str(BY_LABEL[label].freq)
    except KeyError:
        raise ValueError(
            f"Unknown frequency label {label!r}; expected one of "
            f"{', '.join(map(repr, BY_LABEL))}."
        ) from None


def resample_offset(from_label: str, to_label: str) -> str:
    """Return the offset for resampling ``from_label`` onto ``to_label``.

    Resampling only coarsens, so this raises `ValueError` unless ``to_label`` is
    coarser than ``from_label``.
    """
    order = list(BY_LABEL)
    for label in (from_label, to_label):
        if label not in order:
            raise ValueError(
                f"Unknown frequency label {label!r}; expected one of "
                f"{', '.join(map(repr, order))}."
            )
    if order.index(to_label) <= order.index(from_label):
        raise ValueError(
            f"Cannot resample {from_label!r} to {to_label!r}: resampling coarsens, "
            f"so the target must be coarser than the source."
        )
    return offset(to_label)


def time_index(da: xr.DataArray, what: str) -> pd.DatetimeIndex:
    """Return ``da``'s time coordinate as a `pandas.DatetimeIndex`.

    The models that wrap a sequential algorithm (SPLASH, SGAM, RothC) need the
    calendar as well as the values. The time dimension is detected from the data
    rather than assumed to be called ``time``.

    Parameters
    ----------
    da
        A time-bearing array; only its time coordinate is read.
    what
        Human-readable name of ``da``, used in the error raised when it carries
        no time dimension, or more than one.

    Returns
    -------
    pandas.DatetimeIndex
        The time coordinate.
    """
    dim = sole_time_dim(da, what)
    return pd.DatetimeIndex(da.coords[dim].values)


#: How a node behaves in time; see `time_behaviour`.
TimeBehaviour = Literal["pointwise", "record", "stateful"]

#: The attribute `time_behaviour` sets on the function it declares.
_TIME_BEHAVIOUR_ATTR = "__viresco_time_behaviour__"

_F = TypeVar("_F", bound=Callable)


def time_behaviour(behaviour: TimeBehaviour) -> Callable[[_F], _F]:
    """Declare how a node behaves in time.

    ``"pointwise"``: each step is computed from that step's inputs alone, so the
    result does not depend on when the run starts or how long it is. A node with
    no declaration is pointwise.

    ``"record"``: reads a window or the whole record, but carries no state, so
    the result depends on the period run. A growing-season mean, an annual
    maximum, an interpolation between composites.

    ``"stateful"``: integrates a state from an initial condition, so it needs a
    spin-up (a ``<model>_spinup_years`` setting) or an initial state (an
    ``initial_<state>`` input), and is calibrated against data that do not
    drive it.

    The decorator only records the declaration on the function, which it returns
    unchanged, so it composes with Hamilton's and xarray-annotated's decorators
    in any order. The conformance tests check every declaration. See
    ``docs/adr/0003-component-kinds.md``.
    """
    if behaviour not in get_args(TimeBehaviour):
        raise ValueError(
            f"Unknown time behaviour {behaviour!r}; expected one of "
            f"{', '.join(map(repr, get_args(TimeBehaviour)))}."
        )

    def declare(func: _F) -> _F:
        setattr(func, _TIME_BEHAVIOUR_ATTR, behaviour)
        return func

    return declare


def time_behaviour_of(func: Callable) -> TimeBehaviour:
    """Return the time behaviour ``func`` declares, ``"pointwise"`` if none."""
    return getattr(func, _TIME_BEHAVIOUR_ATTR, "pointwise")
