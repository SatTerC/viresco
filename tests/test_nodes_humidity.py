"""`viresco.nodes.humidity`: each variant matches pyrealm, and the key selects it."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import xarray_annotated as xra
from catena import build_driver
from pyrealm.core.hygro import convert_rh_to_vpd, convert_sh_to_vpd
from xarray_annotated.units import UnitError

from viresco.nodes import humidity

DATES = pd.date_range("2020-01-01", periods=4, freq="D")


def _daily(value: float, units: str) -> xr.DataArray:
    return xr.DataArray(
        np.full((4, 2), value),
        dims=["time", "pixel"],
        coords={"time": DATES, "pixel": [0, 1]},
        attrs={"units": units},
    )


TEMPERATURE = _daily(21.0, "degC")
INPUTS = {
    "temperature": TEMPERATURE,
    "dewpoint_temperature": _daily(15.0, "degC"),
    "specific_humidity": _daily(0.006, "kg kg-1"),
    "pressure": _daily(99024.0, "Pa"),
    "relative_humidity": _daily(0.7, "1"),
}


def test_dewpoint_is_saturation_deficit_between_air_and_dewpoint():
    # pyrealm's Magnus equation gives 2.480904 kPa at 21 degC, 1.701591 at 15.
    vpd = humidity.vpd__dewpoint(TEMPERATURE, INPUTS["dewpoint_temperature"])
    np.testing.assert_allclose(vpd.values, 779.31, rtol=1e-3)


def test_specific_humidity_matches_pyrealm_in_pascals():
    vpd = humidity.vpd__specific_humidity(
        TEMPERATURE, INPUTS["specific_humidity"], INPUTS["pressure"]
    )
    expected = convert_sh_to_vpd(
        np.array([0.006]), np.array([21.0]), np.array([99.024])
    )
    np.testing.assert_allclose(vpd.values, expected[0] * 1000)


def test_relative_humidity_matches_pyrealm_in_pascals():
    vpd = humidity.vpd__relative_humidity(TEMPERATURE, INPUTS["relative_humidity"])
    expected = convert_rh_to_vpd(np.array([0.7]), np.array([21.0]))
    np.testing.assert_allclose(vpd.values, expected[0] * 1000)


def test_supersaturation_is_clipped_to_no_deficit():
    vpd = humidity.vpd__dewpoint(TEMPERATURE, _daily(22.0, "degC"))
    assert (vpd.values == 0.0).all()


def test_output_is_stamped_in_pascals():
    with xra.enabled(True):
        vpd = humidity.vpd__dewpoint(TEMPERATURE, INPUTS["dewpoint_temperature"])
    assert vpd.attrs["units"] == "Pa"


def test_contract_rejects_dewpoint_in_kelvin():
    with xra.enabled(True), pytest.raises(UnitError):
        humidity.vpd__dewpoint(TEMPERATURE, _daily(288.15, "K"))


@pytest.mark.parametrize(
    ("config", "needs"),
    [
        ({}, "dewpoint_temperature"),
        ({"vpd_from": "dewpoint"}, "dewpoint_temperature"),
        ({"vpd_from": "specific_humidity"}, "specific_humidity"),
        ({"vpd_from": "relative_humidity"}, "relative_humidity"),
    ],
)
def test_vpd_from_selects_one_variant(config, needs):
    dr = build_driver(["viresco.nodes.humidity"], config)
    upstream = {v.name for v in dr.what_is_upstream_of("vpd") if v.is_external_input}
    sources = {"dewpoint_temperature", "specific_humidity", "relative_humidity"}
    assert upstream & sources == {needs}
    result = dr.execute(["vpd"], inputs={k: INPUTS[k] for k in upstream})
    assert np.isfinite(result["vpd"].values).all()
