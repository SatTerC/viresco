"""The models read dimension names off the data, so none is assumed.

A static scan fails on any dimension name written into the package's source, and
an end-to-end test checks that the models work on whatever names the data has.
A file can name its axes ``date`` and ``site`` rather than ``time`` and ``pixel``.
The end-to-end test runs the four-model example pipeline twice, as generated and
with every input's dimensions renamed, and expects the same numbers on the renamed
axes. The example config's own expressions name ``time``, as a config written for
such a file would not, so the renamed run swaps that name in the config too.
"""

import ast
import re
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import xarray_annotated as xra
from catena import get_final_vars, load_config, load_inputs
from conftest import driver_from_config

from viresco._dims import space_dim
from viresco.scaffold.data_gen import generate_synthetic_data

EXAMPLE_CONFIG = Path(__file__).parent.parent / "recipes" / "config.toml"
RENAMED = {"time": "date", "pixel": "site"}

PACKAGE = Path(__file__).parent.parent / "src" / "viresco"
DIM_NAMES = {"time", "pixel", "site", "date", "x", "y"}
# The synthetic-data generator names the dimensions of the data it makes, and the
# CLI handles no arrays: its 'x' and 'y' are a checkbox marker and a unit.
NOT_SCANNED = {"scaffold", "cli"}


def _docstrings(tree: ast.Module) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, owners)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _dim_names_in(path: Path) -> list[str]:
    """Return each string, keyword or attribute in ``path`` named like a dimension."""
    tree = ast.parse(path.read_text())
    docstrings = _docstrings(tree)
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and node.value in DIM_NAMES
            and id(node) not in docstrings
        ):
            found.append((node.lineno, repr(node.value)))
        elif isinstance(node, ast.keyword) and node.arg in DIM_NAMES:
            found.append((node.value.lineno, f"{node.arg}="))
        elif isinstance(node, ast.Attribute) and node.attr in DIM_NAMES:
            found.append((node.lineno, f".{node.attr}"))
    where = path.relative_to(PACKAGE.parent)
    return [f"{where}:{line}: {name}" for line, name in sorted(found)]


def test_no_dimension_name_is_written_into_the_source():
    """Models take names from `sole_time_dim` and `viresco._dims.space_dim`."""
    hits = [
        hit
        for path in sorted(PACKAGE.rglob("*.py"))
        if not NOT_SCANNED & set(path.relative_to(PACKAGE).parts)
        for hit in _dim_names_in(path)
    ]
    assert not hits, "dimension names in the source:\n" + "\n".join(hits)


def _rename_dims(da: xr.DataArray, mapping: dict[str, str]) -> xr.DataArray:
    return da.rename({old: new for old, new in mapping.items() if old in da.dims})


def _run(config_path: Path, mapping: dict[str, str]) -> dict[str, xr.DataArray]:
    config = load_config(config_path)
    inputs = {
        name: _rename_dims(da, mapping)
        for name, da in load_inputs(config.input_specs).items()
    }
    final_vars: list = get_final_vars(config.output_specs)
    with xra.enabled(True):
        return driver_from_config(config).execute(final_vars, inputs=inputs)


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    """Two years of example inputs, with the example config and a renamed copy."""
    data_dir = tmp_path_factory.mktemp("dim_names")
    config = load_config(EXAMPLE_CONFIG)
    for spec in config.input_specs.values():
        path = data_dir / Path(spec.path).relative_to(EXAMPLE_CONFIG.parent)
        path.parent.mkdir(exist_ok=True)
        spec.path = str(path)
    generate_synthetic_data(config=config, grid=(2, 1), n_days=730, seed=7)

    text = EXAMPLE_CONFIG.read_text()
    (data_dir / "config.toml").write_text(text)
    renamed = re.sub(r"""(["'])time\1""", r"\1date\1", text).replace("time=", "date=")
    (data_dir / "renamed.toml").write_text(renamed)
    return data_dir


def test_models_run_on_any_dimension_names(data_dir):
    reference = _run(data_dir / "config.toml", {})
    renamed = _run(data_dir / "renamed.toml", RENAMED)

    assert set(renamed) == set(reference)
    for name, expected in reference.items():
        actual = renamed[name]
        assert actual.dims == tuple(RENAMED.get(str(d), d) for d in expected.dims), name
        np.testing.assert_array_equal(actual.values, expected.values, err_msg=name)


def _da(*dims: str) -> xr.DataArray:
    coords = {"date": np.arange("2020-01-01", "2020-01-04", dtype="datetime64[D]")}
    shape = [3 if d == "date" else 2 for d in dims]
    return xr.DataArray(
        np.zeros(shape), dims=dims, coords={d: coords[d] for d in dims if d in coords}
    )


class TestSpaceDim:
    def test_ignores_the_time_dimension(self):
        assert space_dim(a=_da("date", "site"), b=_da("site")) == "site"

    def test_allows_an_input_with_no_spatial_dimension(self):
        assert space_dim(a=_da("date", "site"), b=_da()) == "site"

    def test_rejects_two_spatial_dimensions(self):
        with pytest.raises(ValueError, match=r"a has non-time dimensions \['y', 'x'\]"):
            space_dim(a=_da("date", "y", "x"))

    def test_rejects_disagreeing_inputs(self):
        with pytest.raises(ValueError, match="'site' on a; 'pixel' on b"):
            space_dim(a=_da("date", "site"), b=_da("pixel"))

    def test_rejects_no_spatial_dimension(self):
        with pytest.raises(ValueError, match="None of a, b has a spatial dimension"):
            space_dim(a=_da("date"), b=_da())
