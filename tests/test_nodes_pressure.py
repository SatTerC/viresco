"""`viresco.nodes.pressure`: pyrealm's standard atmosphere, on the daily axis."""

import numpy as np
import pandas as pd
import xarray as xr
import xarray_annotated as xra

from viresco.nodes.pressure import pressure

DATES = pd.date_range("2020-01-01", periods=5, freq="D")
TEMPERATURE = xr.DataArray(
    np.full((5, 2), 10.0),
    dims=["time", "pixel"],
    coords={"time": DATES, "pixel": [0, 1]},
    attrs={"units": "degC"},
)
ELEVATION = xr.DataArray(
    [0.0, 1000.0], dims=["pixel"], coords={"pixel": [0, 1]}, attrs={"units": "m"}
)


def test_matches_standard_atmosphere():
    # pyrealm's docstring: 101325 Pa at sea level, 90241.54 Pa at 1000 m.
    patm = pressure(ELEVATION, TEMPERATURE)
    np.testing.assert_allclose(
        patm.isel(time=0).values, [101325.0, 90241.54], rtol=1e-6
    )


def test_is_repeated_along_the_daily_axis():
    patm = pressure(ELEVATION, TEMPERATURE)
    assert patm.dims == TEMPERATURE.dims
    np.testing.assert_array_equal(patm["time"].values, DATES.values)
    assert (patm.std("time") == 0).all()


def test_satisfies_its_daily_contract():
    with xra.enabled(True):
        assert pressure(ELEVATION, TEMPERATURE).attrs["units"] == "Pa"
