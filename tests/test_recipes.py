"""The directory recipes' pipelines still validate and run against their own data.

A recipe directory carries a ``config.toml``, and either the data it runs on or a
``make_data.py`` that writes it. The docs build executes each recipe's notebook,
but `marimo-md-export` exits zero when a cell fails, so these tests are what catch
a recipe that has drifted from the library.
"""

import re
import tomllib
from pathlib import Path

import catena
import pytest
import xarray_annotated as xra
from catena.importing import import_user_module

ROOT = Path(__file__).parent.parent
RECIPES = ROOT / "recipes"
DIRECTORY_RECIPES = sorted(p.parent.name for p in RECIPES.glob("*/config.toml"))


@pytest.fixture(scope="module", autouse=True)
def _recipe_data():
    """Write the inputs of every recipe that generates them."""
    for name in DIRECTORY_RECIPES:
        make_data = RECIPES / name / "make_data.py"
        if make_data.exists():
            import_user_module(str(make_data)).write_inputs()


@pytest.mark.parametrize("name", DIRECTORY_RECIPES)
def test_recipe_dry_runs(name):
    with xra.enabled(True):
        report = catena.dry_run(_config(name, Path(".")))
    statuses = {stage.name: stage.status for stage in report.stages}
    assert "failed" not in statuses.values(), report.stages
    assert statuses["contracts"] == "ok"


@pytest.mark.parametrize("name", DIRECTORY_RECIPES)
def test_recipe_runs(name, tmp_path):
    with xra.enabled(True):
        report = catena.run(_config(name, tmp_path))
    for written in report.written:
        assert written.path.exists()
        assert written.variables


def _config(name: str, results_dir: Path) -> catena.ParsedConfig:
    """Load ``name``'s config, writing its outputs under ``results_dir``."""
    config = catena.load_config(RECIPES / name / "config.toml")
    for spec in config.output_specs.values():
        spec.path = str(results_dir / Path(spec.path).name)
    return config


def test_documented_recipes_match_the_docs_nav():
    """``documented_recipes`` in the justfile lists exactly the Recipes in the nav.

    The justfile exports the notebooks the docs build needs, and the nav links them,
    so a recipe in one and not the other is either a dead link or a stale export.
    """
    justfile = (ROOT / "justfile").read_text()
    match = re.search(r'^documented_recipes := "(.*)"$', justfile, re.MULTILINE)
    assert match, "justfile defines no documented_recipes"
    exported = set(match.group(1).split())

    nav = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["nav"]
    (recipes,) = [section["Recipes"] for section in nav if "Recipes" in section]
    linked = {Path(page).stem for page in recipes}

    assert exported == linked
    assert exported <= set(DIRECTORY_RECIPES)
