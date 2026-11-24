"""The annotations on a module's nodes, keyed by the node name each describes.

catena wires a pipeline by name, so a parameter's annotation describes the node
of that name, and a function's return annotation describes the node the function
produces: its name with any `@config.when` suffix (``vpd__dewpoint``) dropped, or
each field of a returned `TypedDict`, which `@extract_fields` splits into nodes.
"""

import typing
from dataclasses import dataclass
from types import ModuleType

from hamilton.graph_utils import find_functions
from xarray_annotated import Freq, declaration_from_hint


@dataclass(frozen=True)
class Hint:
    """One annotation, with where it was found."""

    node: str
    """The name of the node it describes."""
    where: str
    """``module.function:parameter``, or ``module.function:return``."""
    hint: typing.Any


def node_name(func_name: str) -> str:
    """Return the node a function produces, without a `@config.when` suffix."""
    return func_name.split("__", 1)[0]


def node_hints(module: ModuleType, *, skip: frozenset[str] = frozenset()) -> list[Hint]:
    """Every parameter and output annotation on ``module``'s node functions."""
    hints: list[Hint] = []
    for name, func in find_functions(module):
        if name in skip:
            continue
        where = f"{module.__name__}.{name}"
        for param, hint in typing.get_type_hints(func, include_extras=True).items():
            if param != "return":
                hints.append(Hint(param, f"{where}:{param}", hint))
            elif typing.is_typeddict(hint):
                fields = typing.get_type_hints(hint, include_extras=True)
                hints.extend(
                    Hint(field, f"{where}:return.{field}", field_hint)
                    for field, field_hint in fields.items()
                )
            else:
                hints.append(Hint(node_name(name), f"{where}:return", hint))
    return hints


def declared_freq(hint: typing.Any) -> Freq | None:
    """Return the frequency ``hint`` declares, if any."""
    declared = declaration_from_hint(hint)
    return None if declared is None else declared.freq


def declared_unit(hint: typing.Any) -> str | None:
    """Return the unit ``hint`` declares, as written, if any."""
    declared = declaration_from_hint(hint)
    return None if declared is None or declared.unit is None else str(declared.unit)
