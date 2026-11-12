"""The scaffolding route has to actually produce a pipeline that runs.

The quickstart guide, `recipes/quickstart/demo.py`, teaches that route for SPLASH
alone; `test_quickstart_notebook_runs` runs the guide itself.

`viresco setup` → `viresco data-gen` → `viresco run` is what the quickstart tells
a new user to do, and it is the only path where the two scaffolding halves are
exercised against each other: the config generator decides what a model needs,
and the data generator has to be able to fabricate it.

Nothing else covers that seam. `test_contracts.py` runs `recipes/config.toml`,
which is hand-written — so it validates the models, not the generator. A gap in
the generator (a resample it fails to emit, a variable it leaves unbound, a rate
it coarsens as a mean) shows up here and nowhere else.
"""

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from typer.testing import CliRunner

from viresco.cli import app

MODELS = "splash,pmodel,sgam,rothc"
GRID = ("2", "2")
DURATION = "2y"


@pytest.fixture(scope="module")
def quickstart(tmp_path_factory):
    """Run the documented route end to end, returning the working directory."""
    workdir = tmp_path_factory.mktemp("quickstart")
    (workdir / "outputs").mkdir()
    runner = CliRunner()

    generated = runner.invoke(
        app, ["setup", "-m", MODELS, "-d", "-o", str(workdir / "config.toml")]
    )
    assert generated.exit_code == 0, generated.output

    config = workdir / "config.toml"
    data = runner.invoke(
        app,
        [
            "data-gen",
            str(config),
            "--grid",
            *GRID,
            "--duration",
            DURATION,
        ],
    )
    assert data.exit_code == 0, data.output
    return workdir


class TestQuickstart:
    def test_dry_run_passes(self, quickstart):
        """Catches an unbound input or a contract mismatch without computing."""
        result = CliRunner().invoke(
            app, ["run", str(quickstart / "config.toml"), "--dry-run"]
        )
        assert result.exit_code == 0, result.output

    def test_pipeline_runs_and_writes_every_section(self, quickstart):
        result = CliRunner().invoke(app, ["run", str(quickstart / "config.toml")])
        assert result.exit_code == 0, result.output
        for section in ("daily", "weekly", "monthly"):
            assert (quickstart / "outputs" / f"{section}.nc").exists()

    def test_outputs_are_finite(self, quickstart):
        """A NaN here means synthetic data drove a model outside its domain."""
        CliRunner().invoke(app, ["run", str(quickstart / "config.toml")])
        for section in ("daily", "weekly", "monthly"):
            dataset = xr.open_dataset(quickstart / "outputs" / f"{section}.nc")
            for name, values in dataset.data_vars.items():
                assert not np.isnan(values.values).any(), f"{section}.{name} has NaN"

    def test_soil_carbon_is_physically_plausible(self, quickstart):
        """RothC integrates over the whole run, so it fails loudly if its drivers
        are nonsense — it is the most sensitive check available here."""
        CliRunner().invoke(app, ["run", str(quickstart / "config.toml")])
        monthly = xr.open_dataset(quickstart / "outputs" / "monthly.nc")
        soc = monthly.soil_organic_carbon.values
        assert (soc > 0).all()
        assert 10.0 < soc.mean() < 1000.0


class TestGeneratedConfigShape:
    """What the generator must emit for the four-model pipeline to wire up."""

    def test_observed_gpp_is_loaded_apart_from_the_modelled_one(self, quickstart):
        """Disturbance detection wants observed daily GPP, `gpp_obs`.

        pmodel's GPP is weekly and modelled. Resampling only coarsens, so it
        could not supply a daily consumer anyway, and the distinct name keeps
        `gpp_obs` and `gpp_weekly` from reading as one variable at two
        frequencies.
        """
        config = tomllib.loads((quickstart / "config.toml").read_text())
        assert {"gpp_obs", "lai_obs"} <= set(config["inputs"]["daily"]["vars"])
        loaded = {
            var for section in config["inputs"].values() for var in section["vars"]
        }
        assert "gpp" not in loaded

    def test_sgam_productivity_comes_from_pmodel_not_from_a_file(self, quickstart):
        """The generator has to emit the units bridges or this seam silently rots.

        pmodel reports GPP and LUE in pyrealm's units, under pyrealm's names
        (`gpp_flux`, `lue_photon`). Neither is what sgam consumes. Without a
        bridge node the generator sees two unsatisfied inputs and quietly loads
        them from a file — sgam then runs on synthetic noise, and every other
        check in this file still passes, because the pipeline it produces is
        perfectly well-formed. `lue` in particular matches no rule in the data
        generator's name table, so the fallback would hand sgam gaussian noise
        straddling zero, against a parameter whose PFT maxima are all positive.
        """
        config = tomllib.loads((quickstart / "config.toml").read_text())
        loaded = {
            var for section in config["inputs"].values() for var in section["vars"]
        }
        assert {"lue", "lue_photon", "gpp_flux"}.isdisjoint(loaded)

        nodes = {node["name"]: node for node in config["node"]}
        for target, source in (("gpp", "gpp_flux"), ("lue", "lue_photon")):
            assert nodes[f"{target}_weekly"]["inputs"] == [f"{source}_weekly"]

    def test_a_bridged_variable_is_not_also_resampled(self, quickstart):
        """A bridged node must not also be the target of a resample.

        If the generator emitted a resample onto `gpp_weekly` as well as the
        bridge from `gpp_flux_weekly`, catena would have two definitions of it,
        and the resampled one is the wrong answer.
        """
        config = tomllib.loads((quickstart / "config.toml").read_text())
        node_names = {node["name"] for node in config["node"]}
        for entry in config["resample"]:
            for var in entry["vars"]:
                assert f"{var}_{entry['to']}" not in node_names

    def test_model_outputs_are_resampled_for_coarser_consumers(self, quickstart):
        """sgam produces daily `disturbances` and consumes `disturbances_weekly`."""
        config = (quickstart / "config.toml").read_text()
        assert '"disturbances",' in config

    def test_rates_are_accumulated_not_averaged(self, quickstart):
        """`mm d-1` onto RothC's `mm` is a total: a summing node, not a resample.

        A `[[resample]]` preserves units, so coarsening this one as a mean would
        hand RothC a rate labelled as a total.
        """
        config = (quickstart / "config.toml").read_text()
        for name in ("precipitation_monthly", "potential_evapotranspiration_monthly"):
            assert f'name = "{name}"' in config
            assert f"{name.rsplit('_', 1)[0]}.resample" in config


@pytest.mark.skipif(not shutil.which("dot"), reason="graphviz not installed")
def test_quickstart_notebook_runs(tmp_path):
    """The quickstart guide is a notebook that runs the CLI route, then Python.

    `marimo-md-export` exits zero when a cell fails, so the docs build would
    publish a broken guide; run as a script, a marimo notebook exits non-zero.
    The copy keeps the notebook's working directory out of the repository. The
    notebook draws its graph with `viresco graph --png`, which needs graphviz; CI
    installs it, so the skip only applies to a local run without it.
    """
    notebook = Path(__file__).parent.parent / "recipes" / "quickstart" / "demo.py"
    shutil.copy(notebook, tmp_path / "demo.py")
    result = subprocess.run(
        [sys.executable, str(tmp_path / "demo.py")], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert (tmp_path / "my_pipeline" / "outputs" / "weekly.nc").exists()
