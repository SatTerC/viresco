"""Everything that lists viresco's modules agrees with the registry.

The ``catena.modules`` entry points are the one list of model, driver and
coupling modules
(see `viresco.registry`). The places that cannot read it, the package
``__all__`` lists and the documentation, are checked against it here, so that
adding a module and forgetting one of them fails with a message naming it.
"""

import pkgutil
import tomllib
from importlib import import_module
from pathlib import Path

import pytest
from hamilton.graph_utils import find_functions

from viresco.registry import (
    COUPLINGS,
    DOMAINS,
    DRIVERS,
    MODELS,
    import_registered,
    registered,
)

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"

#: For each package: its pages under `docs/`, and the page indexing all of them
#: with the text it carries for each module, if that index is written by hand.
#: The models overview's table is generated (`scripts/render_catalogue.py`), so
#: it needs no check.
PAGES = {
    MODELS: ("models/{name}.md", None, None),
    DRIVERS: (None, "drivers/index.md", "{{ #{name} }}"),
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
    if index is not None:
        assert entry.format(name=name) in (DOCS / index).read_text(), (
            f"docs/{index} has no entry for {name}"
        )


@pytest.mark.parametrize(("package", "name"), _cases())
def test_module_is_listed_in_the_python_api_page(package, name):
    link = f"(modules/{package}/{name}.md)"
    assert link in (DOCS / "reference/python-api.md").read_text(), (
        f"docs/reference/python-api.md has no row for {package}.{name}"
    )


@pytest.mark.parametrize("name", registered(MODELS))
def test_model_is_listed_on_the_home_page(name):
    assert f"(models/{name}.md)" in (DOCS / "index.md").read_text(), (
        f"docs/index.md does not link the {name} page"
    )


def _models_nav() -> list:
    nav = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["nav"]
    return next(entry["Models"] for entry in nav if "Models" in entry)


@pytest.mark.parametrize(("name", "module"), import_registered(MODELS).items())
def test_model_declares_a_domain_and_sits_under_it_in_the_nav(name, module):
    """The Models nav groups pages by domain, so alternatives sit side by side."""
    domain = getattr(module, "DOMAIN", None)
    assert domain in DOMAINS, f"{name}.DOMAIN is {domain!r}, not one of {DOMAINS}"
    sections = {
        title: pages
        for entry in _models_nav()
        if isinstance(entry, dict)
        for title, pages in entry.items()
    }
    heading = domain.capitalize()
    assert heading in sections, f"the Models nav has no {heading!r} section"
    assert f"models/{name}.md" in sections[heading], (
        f"models/{name}.md is not under {heading!r} in the Models nav"
    )


def test_couplings_have_their_pages():
    for page in ("couplings.md", "reference/modules/viresco.couplings.md"):
        assert (DOCS / page).is_file(), f"docs/{page} is missing"
        assert page in _nav_pages(), f"{page} is not in the zensical.toml nav"
    assert registered(COUPLINGS) == {"couplings": COUPLINGS}


@pytest.mark.parametrize(
    "name",
    [name for name, _ in find_functions(import_registered(COUPLINGS)["couplings"])],
)
def test_each_coupling_is_rendered_on_the_couplings_page(name):
    assert f"::: viresco.couplings.{name}\n" in (DOCS / "couplings.md").read_text()
