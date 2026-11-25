"""Render the documentation's generated tables and graph from the registry.

The snippets, each read from the code so that it cannot drift from it:

- ``models.md``: the models overview table, with each model's domain, frequency,
  time behaviour and alternatives;
- ``variables.md``: every node a registered module reads or writes, with its unit,
  frequency, and the modules that produce and consume it;
- ``components.svg``: one box per model and driver, joined where one consumes what
  another produces, directly or through a coupling;
- ``couplings.md``: each coupling, the key that selects it, and the modules on
  either side;
- ``reference/<model>.md``: each model page's Reference section, from the
  config ``catena init -m <model>`` writes: its settings, inputs, outputs and
  intermediate nodes, each with the unit and frequency it declares and the
  docstring that describes it;
- ``guides/<model>.md``: links to the documented recipes and guides that run
  the model, empty where there are none.

Run through ``just catalogue``, which ``just docs`` runs first. Nothing here is
committed: the pages include the snippets with ``pymdownx.snippets``.
"""

import argparse
import inspect
import re
import tomllib
import typing
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from types import ModuleType, UnionType

import graphviz
import griffe
import tomli_w
from catena.build import build_driver
from catena.scaffold import generate_config
from hamilton.graph_utils import find_functions
from hamilton.node import DependencyType
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
    if typing.get_origin(hint) in (typing.Union, UnionType):
        return any(_is_data(arg) for arg in typing.get_args(hint))
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


def as_inline_html(svg: str) -> str:
    """Strip the SVG down to something markdown will pass through untouched.

    The XML prolog and doctype go because the fragment is inlined into a page
    rather than served as a document. The fixed ``width``/``height`` go too, so
    the ``viewBox`` scales the drawing to its container. A blank line anywhere
    inside would end the raw-HTML block and leave the remainder as literal
    text, so those are collapsed as well.
    """
    svg = svg[svg.index("<svg") :]
    svg = re.sub(r'<svg width="[^"]*" height="[^"]*"', "<svg", svg, count=1)
    return re.sub(r"\n\s*\n+", "\n", svg).strip()


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


@cache
def _griffe_module(name: str) -> griffe.Object | griffe.Alias:
    return griffe.load(name, docstring_parser="numpy")


def _doc_sections(obj: typing.Any) -> list[griffe.DocstringSection]:
    """The parsed numpydoc sections of a function's or class's docstring."""
    found = _griffe_module(obj.__module__)[obj.__qualname__]
    return found.docstring.parsed if found.docstring else []


def _one_line(text: str) -> str:
    """A docstring description as one table cell."""
    return " ".join(text.split()).replace("|", r"\|")


def _documented(func: typing.Any, kind: griffe.DocstringSectionKind) -> dict[str, str]:
    """Each name a function's ``kind`` section documents, with its description."""
    return {
        item.name: _one_line(item.description)
        for section in _doc_sections(func)
        if section.kind is kind
        for item in section.value
    }


def _returns(func: typing.Any) -> str:
    """The description under a function's ``Returns``, else its summary line."""
    returns = _documented(func, griffe.DocstringSectionKind.returns)
    if returns:
        return next(iter(returns.values()))
    text = _doc_sections(func)
    summary = text[0].value if text and text[0].kind.value == "text" else ""
    return _one_line(summary.split("\n\n", 1)[0])


def _field_doc(cls: typing.Any, name: str) -> str:
    """The docstring of a TypedDict's field."""
    found = _griffe_module(cls.__module__)[cls.__qualname__]
    member = found.members.get(name)
    return _one_line(member.docstring.value) if member and member.docstring else ""


def _label(hint: typing.Any) -> tuple[str, str]:
    """A declaration's unit and frequency, as table cells."""
    declared = declaration_from_hint(hint)
    if declared is None:
        return "—", "static"
    unit = "—" if declared.unit is None else f"`{declared.unit}`"
    freq = "static" if declared.freq is None else FREQUENCIES.get(declared.freq, "?")
    return unit, freq


def _has_unit(hint: typing.Any) -> bool:
    declared = declaration_from_hint(hint)
    return declared is not None and declared.unit is not None


def _toml(value: typing.Any) -> str:
    return tomli_w.dumps({"x": value}).removeprefix("x = ").strip()


def _code_list(names: typing.Iterable[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)


def _table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ]
    return "\n".join(lines) + "\n"


def _settings_rows(module: ModuleType) -> list[tuple[str, ...]]:
    """One row per keyword-only setting of any of the module's node functions."""
    nodes: dict[str, list[str]] = defaultdict(list)
    defaults: dict[str, typing.Any] = {}
    docs: dict[str, str] = {}
    for name, func in find_functions(module):
        documented = _documented(func, griffe.DocstringSectionKind.other_parameters)
        for param in inspect.signature(func).parameters.values():
            if param.kind is not inspect.Parameter.KEYWORD_ONLY:
                continue
            nodes[param.name].append(name)
            defaults.setdefault(param.name, param.default)
            if param.name not in docs and documented.get(param.name):
                docs[param.name] = documented[param.name]
    return [
        (
            f"`{setting}`",
            "unset" if defaults[setting] is None else f"`{_toml(defaults[setting])}`",
            _code_list(nodes[setting]),
            docs.get(setting, ""),
        )
        for setting in nodes
    ]


def _output_hint(func: typing.Any, node: str) -> tuple[typing.Any, str]:
    """The hint a node function declares for ``node``, and its description."""
    returned = typing.get_type_hints(func, include_extras=True).get("return")
    if typing.is_typeddict(returned):
        hints = typing.get_type_hints(returned, include_extras=True)
        return hints.get(node), _field_doc(returned, node)
    return returned, _returns(func)


def reference(entry: Module) -> str:
    """A model page's Reference section, relative to ``docs/models/``.

    The inputs and outputs are those of the config ``catena init -m <model>``
    writes, from the variants its settings select by default.
    """
    generated = generate_config([entry.name]).data
    settings = generated.get(entry.name, {})
    dr = build_driver([entry.module.__name__], settings, check_contracts=False)
    nodes = {node.name: node for node in dr.graph.get_nodes()}
    outputs = set(generated.get("outputs", {}).get("vars", []))

    consumed: dict[str, list[tuple[typing.Any, typing.Any, DependencyType]]] = (
        defaultdict(list)
    )
    for node in nodes.values():
        if node.user_defined or not node.originating_functions:
            continue
        func = node.originating_functions[0]
        for dep, (hint, dependency) in node.input_types.items():
            consumed[dep].append((func, hint, dependency))

    input_rows = []
    for name, node in sorted(nodes.items()):
        uses = consumed.get(name, [])
        if not node.user_defined or not any(_is_data(hint) for _, hint, _ in uses):
            continue
        # A consumer declaring a unit first: one that reads the input only for
        # its calendar declares none, and describes it only as that.
        uses.sort(key=lambda use: not _has_unit(use[1]))
        unit, freq = _label(uses[0][1])
        description = next(
            (
                doc
                for func, _, _ in uses
                if (
                    doc := _documented(
                        func, griffe.DocstringSectionKind.parameters
                    ).get(name)
                )
            ),
            "",
        )
        optional = all(dep is DependencyType.OPTIONAL for _, _, dep in uses)
        label = f"`{name}`" + (" (optional)" if optional else "")
        users = _code_list(sorted({func.__name__ for func, _, _ in uses}))
        input_rows.append((label, unit, freq, users, description))

    output_rows, intermediate_rows = [], []
    for name, node in nodes.items():
        if node.user_defined or not node.originating_functions:
            continue
        func = node.originating_functions[0]
        hint, description = _output_hint(func, name)
        if not _is_data(hint) or typing.is_typeddict(hint):
            continue
        unit, freq = _label(hint)
        row = (f"`{name}`", unit, freq, description)
        (output_rows if name in outputs else intermediate_rows).append(row)

    header = ("Unit", "Frequency")
    parts = [
        f"Python API: [`{entry.module.__name__}`](../reference/modules/"
        f"viresco.models/{entry.name}.md)\n"
    ]
    if rows := _settings_rows(entry.module):
        parts += [
            f"### Settings: `[{entry.name}]`\n",
            _table(("Setting", "Default", "Node", "Description"), rows),
        ]
    parts += [
        "### Inputs\n",
        _table(("Input", *header, "Read by", "Description"), input_rows),
        "### Outputs\n",
        _table(("Output", *header, "Description"), output_rows),
    ]
    if intermediate_rows:
        parts += [
            "#### Intermediate nodes\n",
            _table(("Node", *header, "Description"), intermediate_rows),
        ]
    return "\n".join(parts)


RECIPES = ROOT / "recipes"


def _documented_recipes() -> list[str]:
    """The recipes in the Recipes nav, which ``documented_recipes`` must match."""
    nav = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["nav"]
    pages = next(entry["Recipes"] for entry in nav if "Recipes" in entry)
    return [Path(page).stem for page in pages]


def _notebook_title(path: Path) -> str:
    match = re.search(r'app_title="([^"]+)"', path.read_text())
    return match.group(1) if match else path.parent.name


def guides(models: list[str]) -> dict[str, list[tuple[str, str]]]:
    """For each model, the documented guides that run it, as (title, link).

    Links are relative to ``docs/models/``. A recipe runs the models its
    ``config.toml`` has sections for; the quickstart, which has no committed
    config, runs the models its notebook passes to ``catena init -m``.
    """
    found: dict[str, list[tuple[str, str]]] = {model: [] for model in models}
    quickstart = RECIPES / "quickstart" / "demo.py"
    used = set(re.findall(r"catena init(?: -m \w+)*? -m (\w+)", quickstart.read_text()))
    for model in sorted(used & set(models)):
        found[model].append((_notebook_title(quickstart), "../guides/quickstart.md"))
    for recipe in _documented_recipes():
        sections = tomllib.loads((RECIPES / recipe / "config.toml").read_text())
        title = _notebook_title(RECIPES / recipe / "demo.py")
        for model in models:
            if model in sections:
                found[model].append((title, f"../recipes/{recipe}.md"))
    return found


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
    models = [entry for entry in modules if entry.kind == MODELS]
    for directory in ("reference", "guides"):
        (args.output / directory).mkdir(exist_ok=True)
    for entry in models:
        (args.output / "reference" / f"{entry.name}.md").write_text(reference(entry))
    for model, links in guides([entry.name for entry in models]).items():
        lines = "".join(f"- [{title}]({link})\n" for title, link in links)
        text = f"Guides that run this model:\n\n{lines}" if links else ""
        (args.output / "guides" / f"{model}.md").write_text(text)


if __name__ == "__main__":
    main()
