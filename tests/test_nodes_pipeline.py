"""The `viresco.nodes` modules drive the daily P-model through a real config.

The unit tests check each node on its own. This runs them as catena sections, on
data from `viresco data-gen`, so a wiring mistake shows: a variant that asks for
an input no section supplies, a contract a node's output fails downstream, or a
section name that does not resolve.
"""

import numpy as np
import pytest
import xarray as xr
from typer.testing import CliRunner

from viresco.cli import app

CONFIG = """\
[splash]

[pmodel]

[humidity]
vpd_from = "{vpd_from}"

[radiation]
ppfd_from = "{ppfd_from}"

[pressure]

[interpolate]

[inputs.daily]
path = "inputs/daily.nc"
suffix = ""
vars = {daily}

# Composites and the CO2 record arrive coarser than daily, under the names the
# interpolate module expects.
[inputs.weekly]
path = "inputs/weekly.nc"
suffix = "_coarse"
vars = ["co2", "fapar"]

[inputs.static]
path = "inputs/static.nc"
suffix = ""
vars = ["elevation", "max_soil_moisture"]

[outputs.daily]
path = "outputs/daily.nc"
suffix = ""
vars = ["gpp_flux", "vpd", "ppfd", "fapar", "co2", "pressure"]
"""

HUMIDITY_INPUT = {
    "dewpoint": "dewpoint_temperature",
    "specific_humidity": "specific_humidity",
    "relative_humidity": "relative_humidity",
}
RADIATION_INPUT = {"shortwave": ["shortwave_radiation"], "splash": []}


@pytest.mark.parametrize(
    ("vpd_from", "ppfd_from"),
    [
        ("dewpoint", "splash"),
        ("specific_humidity", "shortwave"),
        ("relative_humidity", "shortwave"),
    ],
)
def test_nodes_drive_the_pmodel(tmp_path, monkeypatch, vpd_from, ppfd_from):
    daily = [
        "precipitation",
        "sunshine_fraction",
        "temperature",
        HUMIDITY_INPUT[vpd_from],
        *RADIATION_INPUT[ppfd_from],
    ]
    config = tmp_path / "config.toml"
    config.write_text(
        CONFIG.format(
            vpd_from=vpd_from,
            ppfd_from=ppfd_from,
            daily="[" + ", ".join(f'"{v}"' for v in daily) + "]",
        )
    )
    (tmp_path / "outputs").mkdir()
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    for args in (
        ["data-gen", str(config), "--grid", "2", "2", "--duration", "2y"],
        ["run", str(config), "--dry-run"],
        ["run", str(config)],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output

    outputs = xr.open_dataset(tmp_path / "outputs" / "daily.nc")
    for name, values in outputs.data_vars.items():
        assert np.isfinite(values.values).all(), name
    assert (outputs["gpp_flux"] > 0).any()
