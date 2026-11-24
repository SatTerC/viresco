"""`viresco.couplings`: each conversion, and the keys that select them.

A coupling is ``<target>__<source>``, selected by ``<target>_from = "<source>"``
with no default. The conventions are checked for every function, so a new
coupling is covered as soon as it is written; the conversions are checked one by
one against hand-computed values.
"""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import xarray_annotated as xra
from hamilton import driver
from hamilton.graph_utils import find_functions
from hamilton.settings import ENABLE_POWER_USER_MODE

from viresco import couplings
from viresco.models import rothc
from viresco.registry import MODELS, registered

FUNCTIONS = dict(find_functions(couplings))
DAYS = pd.date_range("2020-01-01", periods=70, freq="D")
WEEKS = pd.date_range("2020-01-01", periods=10, freq="7D")


def _built(module, config: dict) -> set[str]:
    dr = (
        driver.Builder()
        .with_modules(module)
        .with_config({ENABLE_POWER_USER_MODE: True, **config})
        .build()
    )
    return {v.name for v in dr.list_available_variables() if not v.is_external_input}


def _series(values, units: str, dates=DAYS) -> xr.DataArray:
    values = np.broadcast_to(np.asarray(values, dtype=float), (len(dates), 2))
    return xr.DataArray(
        values.copy(),
        dims=["time", "pixel"],
        coords={"time": dates, "pixel": [0, 1]},
        attrs={"units": units},
    )


def _static(value: float, units: str) -> xr.DataArray:
    return xr.DataArray(np.full(2, value), dims=["pixel"], attrs={"units": units})


def test_no_key_adds_no_node():
    """The section is harmless when enabled: nothing exists until a key is set."""
    assert _built(couplings, {}) == set()


@pytest.mark.parametrize("name", sorted(FUNCTIONS))
def test_name_is_target_and_registered_source(name):
    _, sep, source = name.partition("__")
    assert sep, f"{name} is not named <target>__<source>"
    assert source in registered(MODELS), f"{name}: {source!r} is no registered model"


@pytest.mark.parametrize("name", sorted(FUNCTIONS))
def test_target_key_selects_exactly_this_coupling(name):
    target, _, source = name.partition("__")
    assert _built(couplings, {f"{target}_from": source}) == {target}


def test_volumetric_water_content_is_relative_saturation_times_porosity():
    vwc = couplings.volumetric_water_content__splash(
        _series(75.0, "mm"), _static(150.0, "mm"), bucket_porosity=0.4
    )
    np.testing.assert_allclose(vwc.values, 0.2)


def test_aridity_index_is_the_ratio_of_totals():
    pet = _series(np.linspace(1.0, 3.0, len(DAYS))[:, None], "mm d-1")
    rain = _series(4.0, "mm d-1")
    aridity = couplings.aridity_index__splash(pet, rain)
    assert aridity.dims == ("pixel",)
    np.testing.assert_allclose(aridity.values, 2.0 / 4.0)


def test_splash_daily_photon_total_becomes_mean_rate():
    # 1 mol m-2 d-1 is 1e6 umol over 86400 s.
    ppfd = couplings.ppfd__splash(_series(43.2, "mol m-2 d-1"))
    np.testing.assert_allclose(ppfd.values, 500.0)


def test_gpp_flux_becomes_a_daily_rate():
    # 86400 s d-1 x 1e-6 g ug-1.
    gpp = couplings.gpp__pmodel(_series(100.0, "ug m-2 s-1"))
    np.testing.assert_allclose(gpp.values, 8.64)


def test_lue_per_photon_becomes_per_megajoule():
    lue = couplings.lue__pmodel(_series(0.5, "g mol-1"), par_photons_per_mj=4.6)
    np.testing.assert_allclose(lue.values, 2.3)


def test_soil_carbon_input_is_the_monthly_litter_increment():
    """Weekly litter growing by 7 g m-2 is 0.07 t ha-1 a week."""
    litter = _series(7.0 * np.arange(len(WEEKS))[:, None], "g m-2", WEEKS)
    monthly = couplings.soil_carbon_input_monthly__sgam(litter)
    increments = litter.diff("time").resample(time="1ME").sum() * 0.01
    np.testing.assert_allclose(monthly.values, increments.values)
    assert monthly.attrs["units"] == "t ha-1"


def test_outputs_are_stamped_in_their_consumers_units():
    with xra.enabled(True):
        stamped = {
            "m3 m-3": couplings.volumetric_water_content__splash(
                _series(75.0, "mm"), _static(150.0, "mm")
            ),
            "g m-2 d-1": couplings.gpp__pmodel(_series(100.0, "ug m-2 s-1")),
            "g MJ-1": couplings.lue__pmodel(_series(0.5, "g mol-1")),
            "umol m-2 s-1": couplings.ppfd__splash(_series(43.2, "mol m-2 d-1")),
        }
    for units, result in stamped.items():
        assert result.attrs["units"] == units


def test_falloon_inert_organic_matter_is_selected_by_its_key():
    assert "inert_organic_matter" not in _built(rothc, {})
    assert "inert_organic_matter" in _built(
        rothc, {"inert_organic_matter_from": "falloon"}
    )
    iom = rothc.inert_organic_matter__falloon(_static(50.0, "t ha-1"))
    np.testing.assert_allclose(iom.values, 0.049 * 50.0**1.139)
