"""Render the documentation's generated tables and graph from the registry.

Three snippets, each read from the code so that it cannot drift from it:

- ``models.md``: the models overview table, with each model's domain, frequency,
  time behaviour and alternatives;
- ``variables.md``: every node a registered module reads or writes, with its unit,
  frequency, and the modules that produce and consume it;
- ``components.svg``: one box per model and driver, joined where one consumes what
  another produces, directly or through a coupling;
- ``couplings.md``: each coupling, the key that selects it, and the modules on
  either side.

Run through ``just catalogue``, which ``just docs`` runs first. Nothing here is
committed: the pages include the snippets with ``pymdownx.snippets``.
"""

import argparse
import re
import typing
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import graphviz
from hamilton.graph_utils import find_functions
from render_model_graph import as_inline_html
from xarray_annotated import declaration_from_hint

from viresco import temporal
from viresco.registry import COUPLINGS, DOMAINS, DRIVERS, MODELS, import_registered
from viresco.temporal import time_behaviour_of

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"

#: Ordered from least to most a user must think about, so a module's behaviour is
#: the most demanding of its nodes'.
BEHAVIOURS = ("pointwise", "record", "stateful")
FREQUENCIES = {freq: label for label, freq in temporal.BY_LABEL.items()}


@dataclass
class Variable:
    """One node name, as the registered modules declare it."""

    units: set[str] = field(default_factory=set)
    freqs: set[str] = field(default_factory=set)
    producers: set[str] = field(default_factory=set)
    consumers: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Module:
    """A registered module, by kind and section name."""

    kind: str
    name: str
    module: ModuleType

    @property
    def link(self) -> str:
        """Its documentation, relative to ``docs/reference/``."""
        if self.kind == MODELS:
            return f"../models/{self.name}.md"
        if self.kind == DRIVERS:
            return f"../drivers/index.md#{self.name}"
        return "../couplings.md"


def _modules() -> list[Module]:
    return [
        Module(kind, name, module)
        for kind in (MODELS, DRIVERS, COUPLINGS)
        for name, module in import_registered(kind).items()
    ]


def _is_data(hint: typing.Any) -> bool:
    if typing.get_origin(hint) is typing.Annotated:
        hint = typing.get_args(hint)[0]
    return getattr(hint, "__name__", "") == "DataArray"


def _record(variable: Variable, hint: typing.Any) -> None:
    declared = declaration_from_hint(hint)
    if declared is None:
        return
    if declared.unit is not None:
        variable.units.add(str(declared.unit))
    variable.freqs.add(
        "static" if declared.freq is None else FREQUENCIES.get(declared.freq, "?")
    )


def variables(modules: list[Module]) -> dict[str, Variable]:
    """Every data node any registered module reads or writes, by name."""
    found: dict[str, Variable] = defaultdict(Variable)
    for entry in modules:
        for name, func in find_functions(entry.module):
            hints = typing.get_type_hints(func, include_extras=True)
            for param, hint in hints.items():
                if param == "return":
                    outputs = (
                        typing.get_type_hints(hint, include_extras=True)
                        if typing.is_typeddict(hint)
                        else {name.split("__", 1)[0]: hint}
                    )
                    for output, output_hint in outputs.items():
                        if _is_data(output_hint):
                            found[output].producers.add(entry.name)
                            _record(found[output], output_hint)
                elif _is_data(hint):
                    found[param].consumers.add(entry.name)
                    _record(found[param], hint)
    return dict(sorted(found.items()))


def _behaviour(module: ModuleType) -> str:
    """The most demanding behaviour of any of the module's nodes."""
    seen = {time_behaviour_of(func) for _, func in find_functions(module)}
    return max(seen, key=BEHAVIOURS.index)


def _model_behaviour(entry: Module) -> str:
    """The model node's behaviour, then its other nodes that read other steps."""
    main = time_behaviour_of(getattr(entry.module, entry.name))
    others = defaultdict(list)
    for name, func in find_functions(entry.module):
        behaviour = time_behaviour_of(func)
        if name != entry.name and behaviour not in (main, "pointwise"):
            others[behaviour].append(f"`{name}`")
    notes = "; ".join(f"{b}: {', '.join(n)}" for b, n in sorted(others.items()))
    return main.capitalize() + (f" ({notes})" if notes else "")


def _frequency(entry: Module) -> str:
    """The frequency of the model's own node, the one named for the model."""
    func = getattr(entry.module, entry.name)
    returned = typing.get_type_hints(func, include_extras=True)["return"]
    hints = (
        typing.get_type_hints(returned, include_extras=True)
        if typing.is_typeddict(returned)
        else {entry.name: returned}
    )
    for hint in hints.values():
        declared = declaration_from_hint(hint)
        if declared is not None:
            return (
                FREQUENCIES.get(declared.freq, "static") if declared.freq else "static"
            )
    return "static"


def _title(name: str, *, short: bool = False) -> str:
    """A model page's heading, or with ``short`` its front-matter title."""
    text = (DOCS / "models" / f"{name}.md").read_text()
    pattern = r"^title: (.+)$" if short else r"^# (.+)$"
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1) if match else name


def _provides(entry: Module, found: dict[str, Variable]) -> set[str]:
    """What a model makes: its own outputs, and those of couplings from it."""
    provided = {name for name, var in found.items() if entry.name in var.producers}
    coupling_module = import_registered(COUPLINGS)["couplings"]
    for function_name, _ in find_functions(coupling_module):
        target, _, source = function_name.partition("__")
        if source == entry.name:
            provided.add(target)
    return provided


def models_table(modules: list[Module], found: dict[str, Variable]) -> str:
    """The models overview table, relative to ``docs/models/``."""
    models = [entry for entry in modules if entry.kind == MODELS]
    provides = {entry.name: _provides(entry, found) for entry in models}
    rows = [
        "| Model | Domain | Frequency | Time behaviour | Alternatives |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in sorted(models, key=lambda e: (_domain_order(e.module.DOMAIN), e.name)):
        alternatives = ", ".join(
            f"[{_title(other.name, short=True)}]({other.name}.md)"
            for other in models
            if other.name != entry.name and provides[entry.name] & provides[other.name]
        )
        rows.append(
            f"| [{_title(entry.name)}]({entry.name}.md) "
            f"| {entry.module.DOMAIN.capitalize()} "
            f"| {_frequency(entry).capitalize()} "
            f"| {_model_behaviour(entry)} "
            f"| {alternatives or '—'} |"
        )
    return "\n".join(rows) + "\n"


def _domain_order(domain: str) -> int:
    return DOMAINS.index(domain)


def _links(names: set[str], by_name: dict[str, Module]) -> str:
    return ", ".join(f"[{n}]({by_name[n].link})" for n in sorted(names)) or "—"


def variables_table(modules: list[Module], found: dict[str, Variable]) -> str:
    """The variable catalogue, relative to ``docs/reference/``."""
    by_name = {entry.name: entry for entry in modules}
    rows = [
        "| Variable | Units | Frequency | Produced by | Consumed by |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, var in found.items():
        internal = (
            len(var.producers) == 1
            and var.consumers == var.producers
            and by_name[next(iter(var.producers))].kind == MODELS
        )
        label = f"`{name}`" + (" (internal)" if internal else "")
        rows.append(
            f"| {label} | {', '.join(f'`{u}`' for u in sorted(var.units)) or '—'} "
            f"| {', '.join(sorted(var.freqs)) or '—'} "
            f"| {_links(var.producers, by_name)} "
            f"| {_links(var.consumers, by_name)} |"
        )
    return "\n".join(rows) + "\n"


def couplings_table(modules: list[Module], found: dict[str, Variable]) -> str:
    """The couplings table, relative to ``docs/``."""
    by_name = {entry.name: entry for entry in modules}
    coupling_module = import_registered(COUPLINGS)["couplings"]
    rows = [
        "| Produces | From | Selected by | Consumed by | Time behaviour |",
        "| --- | --- | --- | --- | --- |",
    ]
    for function_name, func in find_functions(coupling_module):
        target, _, source = function_name.partition("__")
        consumers = {
            consumer
            for name, var in found.items()
            if _base(name) == _base(target)
            for consumer in var.consumers
        } - {"couplings"}
        links = ", ".join(
            f"[{n}]({by_name[n].link.removeprefix('../')})" for n in sorted(consumers)
        )
        rows.append(
            f"| [`{target}`](#viresco.couplings.{function_name}) "
            f"| [{source}](models/{source}.md) "
            f'| `{target}_from = "{source}"` '
            f"| {links or '—'} "
            f"| {time_behaviour_of(func).capitalize()} |"
        )
    return "\n".join(rows) + "\n"


def _base(name: str) -> str:
    return re.sub(r"_(weekly|monthly)$", "", name)


def components_graph(modules: list[Module], found: dict[str, Variable]) -> str:
    """One box per model and driver, an edge wherever one feeds another."""
    graph = graphviz.Digraph(
        graph_attr={"rankdir": "LR", "bgcolor": "transparent", "fontsize": "11"},
        node_attr={"shape": "box", "style": "rounded", "fontsize": "11"},
        edge_attr={"fontsize": "9"},
    )
    components = [entry for entry in modules if entry.kind != COUPLINGS]
    for entry in components:
        behaviour = (
            time_behaviour_of(getattr(entry.module, entry.name))
            if entry.kind == MODELS
            else _behaviour(entry.module)
        )
        style = "rounded,bold" if behaviour == "stateful" else "rounded"
        graph.node(entry.name, f"{entry.name}\n({behaviour})", style=style)

    produced = defaultdict(set)
    consumed = defaultdict(set)
    for name, var in found.items():
        for producer in var.producers:
            produced[producer].add(_base(name))
        for consumer in var.consumers:
            consumed[consumer].add(_base(name))

    labels: dict[tuple[str, str], set[str]] = defaultdict(set)
    for source in components:
        for target in components:
            if source.name != target.name:
                for name in produced[source.name] & consumed[target.name]:
                    labels[(source.name, target.name)].add(name)
    coupling_module = import_registered(COUPLINGS)["couplings"]
    for function_name, _ in find_functions(coupling_module):
        made, _, source = function_name.partition("__")
        for target in components:
            if target.name != source and _base(made) in consumed[target.name]:
                labels[(source, target.name)].add(f"{_base(made)} (coupling)")
    for (source, target), names in sorted(labels.items()):
        graph.edge(source, target, label="\n".join(sorted(names)))
    return as_inline_html(graph.pipe(format="svg", encoding="utf-8")) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Directory for the snippets.")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    modules = _modules()
    found = variables(modules)
    (args.output / "models.md").write_text(models_table(modules, found))
    (args.output / "variables.md").write_text(variables_table(modules, found))
    (args.output / "components.svg").write_text(components_graph(modules, found))
    (args.output / "couplings.md").write_text(couplings_table(modules, found))


if __name__ == "__main__":
    main()
