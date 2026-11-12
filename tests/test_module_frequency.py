"""Each model module runs at exactly one frequency.

SPLASH is daily, the P-model and SGAM weekly, RothC monthly. A node that does not
fit its model's frequency belongs in `viresco.models.shared`, which is exempt.
Without this test the rule would only be remembered, and the next node to break
it would land in whichever model happened to need it.

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
    pmodel: temporal.WEEKLY,
    sgam: temporal.WEEKLY,
    rothc: temporal.MONTHLY,
}


def _node_hints(module: ModuleType) -> dict[str, typing.Any]:
    """Every parameter and output hint on the module's public node functions.

    A model returning a `TypedDict` contributes one hint per field, since
    `@extract_fields` splits it into one node per field.
    """
    hints: dict[str, typing.Any] = {}
    for name, func in vars(module).items():
        if name.startswith("_") or not inspect.isfunction(func):
            continue
        if func.__module__ != module.__name__:
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
    declared = {
        name: freq
        for name, hint in _node_hints(module).items()
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
