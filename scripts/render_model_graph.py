"""Render one model's DAG to an HTML snippet for its documentation page.

`catena.build_graph` visualises a whole pipeline, so this builds the smallest
config that exercises a single model — the model's own section plus the inputs
and outputs `viresco.testing.config_gen` infers for it — and graphs that. The
I/O paths in the generated config are never opened: building the graph reads
the DAG's contracts, not the data.

The snippet is drawn with dotdoc: each node a registered module's function
defines links to that function's entry in the API reference and previews it on
hover, buttons above the graph zoom it and expand it to the window, and its
fills follow the theme's dark scheme. Inputs, config and the fields a node
extracts are left unlinked.

Run through ``just graph <model>``. The snippet is not committed: ``just docs``
regenerates every model's graph before each build. Needs the Graphviz ``dot``
binary.
"""

import argparse
from collections.abc import Callable
from functools import cache
from pathlib import Path

import graphviz
from catena import build_graph
from dotdoc import autoref, graph_html
from hamilton.graph_types import HamiltonNode
from hamilton.graph_utils import find_functions

from viresco.registry import import_all
from viresco.testing.config_gen import generate_config

#: Placeholder I/O paths. `generate_config` requires them; nothing reads them.
PATHS = {
    "inputs_daily": "inputs/daily.nc",
    "inputs_weekly": "inputs/weekly.nc",
    "inputs_monthly": "inputs/monthly.nc",
    "inputs_static": "inputs/static.nc",
    "outputs_daily": "outputs/daily.nc",
    "outputs_weekly": "outputs/weekly.nc",
    "outputs_monthly": "outputs/monthly.nc",
}


@cache
def identifiers() -> dict[Callable, str]:
    """Each registered module's node functions, to their API reference identifier.

    The identifier is the registered module's path, not ``fn.__module__``, so a
    node defined in a model subpackage's submodule links to where the
    subpackage's page documents it.
    """
    return {
        fn: f"{module.__name__}.{name}"
        for module in import_all().values()
        for name, fn in find_functions(module)
    }


def link(node: HamiltonNode, fn: Callable | None) -> str | None:
    """Link a node a registered module defines to its API reference entry."""
    identifier = identifiers().get(fn) if fn is not None else None
    return None if identifier is None else autoref(identifier)


def digraph(model: str) -> graphviz.Digraph:
    """Draw ``model``'s DAG, each node linked as `link` says."""
    config = generate_config(builtin_models=[model], custom_modules=[], paths=PATHS)
    return build_graph(config.parse(), link=link)


def render(model: str) -> str:
    """Return the HTML snippet for ``model``'s DAG, on one line."""
    return graph_html(digraph(model), controls=True, dark="auto")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Model name, e.g. 'splash'.")
    parser.add_argument("output", type=Path, help="Destination .html path.")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(args.model) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
