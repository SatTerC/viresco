"""Each model module runs at exactly one frequency.

SPLASH and the P-model are daily, SGAM weekly, RothC monthly. A node that does not
fit its model's frequency stays in that model's module only if that model alone
uses it, and only by name in `OFF_FREQUENCY`; see
`docs/adr/0001-node-names-and-module-frequency.md`. Without this test the rule
would only be remembered, and the next node to break it would pass unnoticed.

Static nodes and inputs have no time axis, so declare no `Freq` and are not
counted.
"""

import inspect
import typing
from types import ModuleType

import pytest
from xarray_annotated import Freq, declaration_from_hint

from viresco import temporal
from viresco.models import pmodel, rothc, sgam, splash

MODEL_FREQUENCIES = {
    splash: temporal.DAILY,
    pmodel: temporal.DAILY,
    sgam: temporal.WEEKLY,
    rothc: temporal.MONTHLY,
}

#: Nodes allowed to run at another frequency than their module, each used by
#: that model alone: SGAM's disturbance detection runs on daily observations.
OFF_FREQUENCY: set[tuple[ModuleType, str]] = {
    (sgam, "disturbances"),
}


def _qualname(entry: tuple[ModuleType, str]) -> str:
    module, name = entry
    return f"{module.__name__}.{name}"


def _node_hints(
    module: ModuleType, *, skip: frozenset[str] = frozenset()
) -> dict[str, typing.Any]:
    """Every parameter and output hint on the module's public node functions.

    A model returning a `TypedDict` contributes one hint per field, since
    `@extract_fields` splits it into one node per field. Functions named in
    ``skip`` are left out.
    """
    hints: dict[str, typing.Any] = {}
    for name, func in vars(module).items():
        if name.startswith("_") or not inspect.isfunction(func):
            continue
        if func.__module__ != module.__name__ or name in skip:
            continue
        for param, hint in typing.get_type_hints(func, include_extras=True).items():
            if param == "return" and typing.is_typeddict(hint):
                hints.update(typing.get_type_hints(hint, include_extras=True))
            else:
                hints[f"{name}:{param}"] = hint
    return hints


def _declared_freq(hint: typing.Any) -> Freq | None:
    declared = declaration_from_hint(hint)
    return None if declared is None else declared.freq


@pytest.mark.parametrize(
    ("module", "expected"),
    MODEL_FREQUENCIES.items(),
    ids=lambda value: getattr(value, "__name__", str(value)),
)
def test_model_module_declares_one_frequency(module, expected):
    allowed = frozenset(name for mod, name in OFF_FREQUENCY if mod is module)
    declared = {
        name: freq
        for name, hint in _node_hints(module, skip=allowed).items()
        if (freq := _declared_freq(hint)) is not None
    }
    assert declared, f"{module.__name__} declares no frequency at all"
    stray = {name: freq for name, freq in declared.items() if freq != expected}
    assert not stray, f"{module.__name__} runs at {expected}, but: {stray}"


@pytest.mark.parametrize(
    "module",
    MODEL_FREQUENCIES,
    ids=lambda module: module.__name__,
)
def test_coarse_series_declare_their_frequency(module):
    """A `_weekly` or `_monthly` name with no `Freq` escapes the contract check.

    Daily and static are both bare, so only the coarse suffixes say a name is a
    time series. Those at least must not go undeclared.
    """
    undeclared = [
        name
        for name, hint in _node_hints(module).items()
        if name.endswith(("_weekly", "_monthly")) and _declared_freq(hint) is None
    ]
    assert not undeclared


@pytest.mark.parametrize(
    ("module", "name"),
    sorted(OFF_FREQUENCY, key=_qualname),
    ids=lambda value: getattr(value, "__name__", str(value)),
)
def test_off_frequency_entries_are_needed(module, name):
    """Each allow-listed node exists and really declares another frequency.

    Otherwise the entry is stale, and would quietly exempt whatever next takes
    that name.
    """
    func = getattr(module, name, None)
    assert inspect.isfunction(func), f"{module.__name__}.{name} no longer exists"
    hints = typing.get_type_hints(func, include_extras=True)
    freqs = {_declared_freq(hint) for hint in hints.values()} - {None}
    assert freqs - {MODEL_FREQUENCIES[module]}, (
        f"{module.__name__}.{name} declares no off-frequency contract"
    )
