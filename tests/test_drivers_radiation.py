"""`viresco.drivers.radiation`: PPFD from shortwave, unless a coupling supplies it."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import xarray_annotated as xra
from catena import build_driver

from viresco.drivers import radiation

DATES = pd.date_range("2020-01-01", periods=4, freq="D")


def _daily(value: float, units: str) -> xr.DataArray:
    return xr.DataArray(
        np.full((4, 2), value),
        dims=["time", "pixel"],
        coords={"time": DATES, "pixel": [0, 1]},
        attrs={"units": units},
    )


def test_shortwave_is_par_share_times_photon_content():
    ppfd = radiation.ppfd__shortwave(_daily(200.0, "W m-2"))
    np.testing.assert_allclose(ppfd.values, 200.0 * 0.45 * 4.57)


def test_shortwave_settings_are_used():
    ppfd = radiation.ppfd__shortwave(
        _daily(200.0, "W m-2"), par_fraction=0.5, par_photons_per_mj=4.6
    )
    np.testing.assert_allclose(ppfd.values, 200.0 * 0.5 * 4.6)


def test_output_is_stamped_in_the_pmodel_units():
    with xra.enabled(True):
        ppfd = radiation.ppfd__shortwave(_daily(200.0, "W m-2"))
    assert ppfd.attrs["units"] == "umol m-2 s-1"


def test_the_splash_coupling_turns_radiation_off():
    """With ``ppfd_from = "splash"`` the coupling, not this module, makes ppfd."""
    dr = build_driver(["viresco.drivers.radiation"], {"ppfd_from": "splash"})
    assert "ppfd" not in {v.name for v in dr.list_available_variables()}


@pytest.mark.parametrize(
    ("config", "needs"),
    [
        ({}, "shortwave_radiation"),
        ({"ppfd_from": "shortwave"}, "shortwave_radiation"),
        ({"ppfd_from": "splash"}, "estimated_ppfd"),
    ],
)
def test_ppfd_from_selects_one_variant(config, needs):
    dr = build_driver(["viresco.drivers.radiation", "viresco.couplings"], config)
    upstream = {
        v.name
        for v in dr.what_is_upstream_of("ppfd")
        if v.is_external_input and v.name in {"shortwave_radiation", "estimated_ppfd"}
    }
    assert upstream == {needs}
