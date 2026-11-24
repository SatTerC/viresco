"""A generated config stops a pipeline whose input files are on different grids.

catena checks that gridded inputs share a grid only when a config asks it to, and
without the check xarray's default inner join silently drops the cells that do not
line up. `viresco.testing.generate_config` therefore writes `crs_equal` and
`coords_equal` checks into every config it generates; these tests run them
against the synthetic data's files.
"""

from pathlib import Path

import catena
import pytest
import xarray as xr
from catena.pipeline import DryRunError

from viresco.testing import generate_config
from viresco.testing.data_gen import generate_synthetic_data

MODELS = ["splash", "pmodel", "sgam", "rothc"]


@pytest.fixture
def config_path(tmp_path) -> Path:
    paths = {
        f"{kind}_{freq}": f"{kind}/{freq}.nc"
        for kind in ("inputs", "outputs")
        for freq in ("daily", "weekly", "monthly", "static")
    }
    path = tmp_path / "config.toml"
    path.write_text(generate_config(MODELS, [], paths).dumps())
    for kind in ("inputs", "outputs"):
        (tmp_path / kind).mkdir()
    generate_synthetic_data(catena.load_config(path), grid=(2, 2), n_days=400)
    return path


def _rewrite(path: Path, change) -> None:
    with xr.open_dataset(path) as ds:
        changed = change(ds.load())
    changed.to_netcdf(path)


def _failures(config_path: Path) -> str:
    with pytest.raises(DryRunError) as raised:
        catena.dry_run(config_path)
    return str(raised.value)


def test_generated_inputs_pass(config_path):
    report = catena.dry_run(config_path)
    statuses = {stage.name: stage.status for stage in report.stages}
    assert statuses["checks"] == "ok", report.stages


def test_shifted_grid_fails(config_path):
    _rewrite(
        config_path.parent / "inputs/static.nc",
        lambda ds: ds.assign_coords(x=ds["x"] + 0.5),
    )
    assert "coordinate 'x' values differ" in _failures(config_path)


def test_different_crs_fails(config_path):
    def other_ellipsoid(ds: xr.Dataset) -> xr.Dataset:
        ds["crs"].attrs["inverse_flattening"] = 298.257222101  # GRS 80
        return ds

    _rewrite(config_path.parent / "inputs/static.nc", other_ellipsoid)
    assert "CRS differs" in _failures(config_path)
