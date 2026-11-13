"""`viresco.nodes.radiation`: both routes to PPFD, and the key that picks one."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import xarray_annotated as xra
from catena import build_driver

from viresco.nodes import radiation

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


def test_splash_daily_total_becomes_mean_rate():
    # 1 mol m-2 d-1 is 1e6 umol over 86400 s.
    ppfd = radiation.ppfd__splash(_daily(43.2, "mol m-2 d-1"))
    np.testing.assert_allclose(ppfd.values, 500.0)


def test_outputs_are_stamped_in_the_pmodel_units():
    with xra.enabled(True):
        for ppfd in (
            radiation.ppfd__shortwave(_daily(200.0, "W m-2")),
            radiation.ppfd__splash(_daily(43.2, "mol m-2 d-1")),
        ):
            assert ppfd.attrs["units"] == "umol m-2 s-1"


@pytest.mark.parametrize(
    ("config", "needs"),
    [
        ({}, "shortwave_radiation"),
        ({"ppfd_from": "shortwave"}, "shortwave_radiation"),
        ({"ppfd_from": "splash"}, "estimated_ppfd"),
    ],
)
def test_ppfd_from_selects_one_variant(config, needs):
    dr = build_driver(["viresco.nodes.radiation"], config)
    upstream = {
        v.name
        for v in dr.what_is_upstream_of("ppfd")
        if v.is_external_input and v.name in {"shortwave_radiation", "estimated_ppfd"}
    }
    assert upstream == {needs}
