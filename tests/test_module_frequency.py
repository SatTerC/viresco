"""Each model module runs at exactly one frequency.

SPLASH and the P-model are daily, SGAM weekly, RothC monthly, but the test does not
list them: every registered model must declare one frequency, whichever it is, so
a new model is checked as soon as it is registered. A node that does not
fit its model's frequency stays in that model's module only if that model alone
uses it, and only by name in `OFF_FREQUENCY`; see
`docs/adr/0001-node-names-and-module-frequency.md`. Without this test the rule
would only be remembered, and the next node to break it would pass unnoticed.

Static nodes and inputs have no time axis, so declare no `Freq` and are not
counted. A module with no time-varying node at all is static, and passes.
"""

import inspect
import typing
from types import ModuleType

import pytest
import toy_subpackage
from hints import declared_freq, node_hints
from xarray_annotated import Freq

from viresco.models import sgam
from viresco.registry import MODELS, import_registered

#: The registered models, and a test-only model written as a subpackage, whose
#: node lives in a submodule: if its frequency is not found, nor would a real
#: subpackage's be.
MODEL_MODULES = [*import_registered(MODELS).values(), toy_subpackage]

#: Nodes allowed to run at another frequency than their module, each used by
#: that model alone: SGAM's disturbance detection runs on daily observations.
OFF_FREQUENCY: set[tuple[ModuleType, str]] = {
    (sgam, "disturbances"),
}


def _qualname(entry: tuple[ModuleType, str]) -> str:
    module, name = entry
    return f"{module.__name__}.{name}"


def _module_frequency(module: ModuleType) -> Freq | None:
    """Return the one frequency ``module`` declares outside `OFF_FREQUENCY`.

    None for a static module, one whose nodes declare no frequency at all, such
    as a set of pedotransfer functions.
    """
    allowed = frozenset(name for mod, name in OFF_FREQUENCY if mod is module)
    declared: dict[Freq, list[str]] = {}
    for hint in node_hints(module, skip=allowed):
        if (freq := declared_freq(hint.hint)) is not None:
            declared.setdefault(freq, []).append(hint.where)
    assert len(declared) <= 1, (
        f"{module.__name__} declares more than one frequency: {declared}"
    )
    return next(iter(declared), None)


@pytest.mark.parametrize("module", MODEL_MODULES, ids=lambda module: module.__name__)
def test_model_module_declares_one_frequency(module):
    _module_frequency(module)


def test_a_subpackage_frequency_is_found():
    """The toy's only node is in a submodule; missing it would make it static."""
    assert _module_frequency(toy_subpackage) is not None


@pytest.mark.parametrize("module", MODEL_MODULES, ids=lambda module: module.__name__)
def test_coarse_series_declare_their_frequency(module):
    """A `_weekly` or `_monthly` name with no `Freq` escapes the contract check.

    Daily and static are both bare, so only the coarse suffixes say a name is a
    time series. Those at least must not go undeclared.
    """
    undeclared = [
        hint.where
        for hint in node_hints(module)
        if hint.node.endswith(("_weekly", "_monthly"))
        and declared_freq(hint.hint) is None
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
    freqs = {declared_freq(hint) for hint in hints.values()} - {None}
    assert freqs - {_module_frequency(module)}, (
        f"{module.__name__}.{name} declares no off-frequency contract"
    )
