"""A node name means one quantity, in one unit, at one frequency.

catena wires a pipeline by name, so every module that reads or writes
``shortwave_radiation`` is talking about the same node, and a pipeline holding
two of them passes one array to each. Two declared units for one name means
that no data can satisfy both, which catena reports only once someone builds
that particular pipeline. This checks every pair of registered modules now. See
`docs/adr/0003-component-kinds.md`.
"""

from collections import defaultdict
from collections.abc import Callable

import pytest
from hints import declared_freq, declared_unit, node_hints

from viresco.registry import import_all

HINTS = [hint for module in import_all().values() for hint in node_hints(module)]


def _clashes(declared: Callable) -> dict[str, dict[str, list[str]]]:
    by_name: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for hint in HINTS:
        if (value := declared(hint.hint)) is not None:
            by_name[hint.node][str(value)].append(hint.where)
    return {name: dict(seen) for name, seen in by_name.items() if len(seen) > 1}


@pytest.mark.parametrize(
    ("what", "declared"), [("unit", declared_unit), ("frequency", declared_freq)]
)
def test_a_name_has_one_declaration(what, declared):
    clashes = _clashes(declared)
    assert not clashes, f"names declared with more than one {what}: {clashes}"
