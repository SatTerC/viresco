"""Everything that lists viresco's modules agrees with the registry.

The ``catena.modules`` entry points are the one list of model and node modules
(see `viresco.registry`). The places that cannot read it, the package
``__all__`` lists and the documentation, are checked against it here, so that
adding a module and forgetting one of them fails with a message naming it.
"""

import pkgutil
import tomllib
from importlib import import_module
from pathlib import Path

import pytest

from viresco.registry import MODELS, NODES, registered

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"

#: For each package: its pages under `docs/`, the page indexing all of them, and
#: the text that index carries for each module.
PAGES = {
    MODELS: ("models/{name}.md", "models/index.md", "({name}.md)"),
    NODES: (None, "nodes/index.md", "{{ #{name} }}"),
}


def _nav_pages() -> set[str]:
    """Every page in the zensical nav, however deeply nested."""

    def walk(entry) -> list[str]:
        if isinstance(entry, str):
            return [entry]
        if isinstance(entry, dict):
            return [page for value in entry.values() for page in walk(value)]
        return [page for item in entry for page in walk(item)]

    nav = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["nav"]
    return set(walk(nav))


def _cases() -> list[tuple[str, str]]:
    return [(package, name) for package in PAGES for name in registered(package)]


@pytest.mark.parametrize("package", PAGES)
def test_every_module_in_the_package_is_registered(package):
    """A module with no entry point is invisible to catena and to every check."""
    found = {
        info.name
        for info in pkgutil.iter_modules(import_module(package).__path__)
        if not info.name.startswith("_")
    }
    assert found == set(registered(package)), (
        f"modules in {package} without a `catena.modules` entry point in "
        f"pyproject.toml: {sorted(found - set(registered(package)))}; "
        "run `uv sync` after adding one"
    )


@pytest.mark.parametrize("package", PAGES)
def test_package_all_matches_the_registry(package):
    assert sorted(import_module(package).__all__) == list(registered(package))


@pytest.mark.parametrize(("package", "name"), _cases())
def test_section_name_is_the_module_name(package, name):
    assert registered(package)[name] == f"{package}.{name}"


@pytest.mark.parametrize(("package", "name"), _cases())
def test_module_has_a_reference_page_in_the_nav(package, name):
    page = f"reference/modules/{package}/{name}.md"
    assert (DOCS / page).is_file(), f"docs/{page} is missing"
    assert f"::: {package}.{name}" in (DOCS / page).read_text()
    assert page in _nav_pages(), f"{page} is not in the zensical.toml nav"


@pytest.mark.parametrize(("package", "name"), _cases())
def test_module_has_a_docs_page_in_the_nav(package, name):
    page_pattern, index, entry = PAGES[package]
    if page_pattern is not None:
        page = page_pattern.format(name=name)
        assert (DOCS / page).is_file(), f"docs/{page} is missing"
        assert page in _nav_pages(), f"{page} is not in the zensical.toml nav"
    assert entry.format(name=name) in (DOCS / index).read_text(), (
        f"docs/{index} has no entry for {name}"
    )
