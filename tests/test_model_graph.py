"""Checks the linked DAG each model page includes (`scripts/render_model_graph.py`)."""

import runpy
import shutil
from pathlib import Path

import pytest
from hamilton.graph_utils import find_functions

from viresco.registry import MODELS, import_registered

SCRIPT = Path(__file__).parents[1] / "scripts" / "render_model_graph.py"
MODULES = import_registered(MODELS)


@pytest.fixture(scope="module")
def script():
    return runpy.run_path(str(SCRIPT))


@pytest.mark.parametrize("model", MODULES)
def test_every_drawn_function_of_the_model_links_to_its_api_entry(script, model):
    # Only the variants the default config selects are drawn, each as a node
    # named for the function without its `__<variant>` suffix.
    source = script["digraph"](model).source
    module = MODULES[model]
    variants = {}
    for name, _ in find_functions(module):
        variants.setdefault(name.split("__")[0], []).append(name)
    drawn = [node for node in variants if f"\n\t{node} [label=" in source]
    assert drawn
    for node in drawn:
        urls = [f'URL="autoref:{module.__name__}.{name}"' for name in variants[node]]
        assert sum(url in source for url in urls) == 1, node


@pytest.mark.parametrize("model", MODULES)
def test_only_registered_functions_are_linked(script, model):
    identifiers = set(script["identifiers"]().values())
    source = script["digraph"](model).source
    linked = {part.split('"', 1)[0] for part in source.split('URL="autoref:')[1:]}
    assert linked <= identifiers


@pytest.mark.skipif(shutil.which("dot") is None, reason="needs Graphviz's dot")
@pytest.mark.parametrize("model", MODULES)
def test_snippet_is_one_block_with_a_preview_per_link(script, model):
    source = script["digraph"](model).source
    snippet = script["render"](model)
    links = source.count('URL="autoref:')
    assert snippet.count("<autoref ") == links
    assert snippet.count("data-preview") == links
    assert "\n\n" not in snippet.strip()
