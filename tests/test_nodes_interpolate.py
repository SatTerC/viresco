"""`viresco.nodes.interpolate`: coarse series onto the daily axis."""

import numpy as np
import pandas as pd
import xarray as xr
import xarray_annotated as xra

from viresco.nodes.interpolate import co2, fapar

DATES = pd.date_range("2020-01-01", periods=10, freq="D")
TEMPERATURE = xr.DataArray(
    np.full((10, 2), 10.0),
    dims=["time", "pixel"],
    coords={"time": DATES, "pixel": [0, 1]},
    attrs={"units": "degC"},
)


def _composites(values: list[list[float]], dates: list[str]) -> xr.DataArray:
    return xr.DataArray(
        values,
        dims=["time", "pixel"],
        coords={"time": pd.to_datetime(dates), "pixel": [0, 1]},
        attrs={"units": "1"},
    )


def test_fapar_is_linear_between_composites_and_held_at_the_ends():
    coarse = _composites([[0.2, 0.2], [0.8, 0.8]], ["2020-01-03", "2020-01-06"])
    daily = fapar(coarse, TEMPERATURE).sel(pixel=0).values
    np.testing.assert_allclose(daily[:3], 0.2)
    np.testing.assert_allclose(daily[3:5], [0.4, 0.6])
    np.testing.assert_allclose(daily[5:], 0.8)


def test_fapar_gap_is_bridged_per_pixel():
    coarse = _composites(
        [[0.2, 0.2], [np.nan, 0.5], [0.8, 0.8]],
        ["2020-01-01", "2020-01-04", "2020-01-07"],
    )
    daily = fapar(coarse, TEMPERATURE)
    np.testing.assert_allclose(daily.sel(time="2020-01-04", pixel=0), 0.5)
    np.testing.assert_allclose(daily.sel(time="2020-01-02", pixel=1), 0.3)
    assert np.isfinite(daily.values).all()


def test_fapar_stays_in_range():
    coarse = _composites([[-0.01, 0.5], [1.02, 0.5]], ["2020-01-01", "2020-01-10"])
    daily = fapar(coarse, TEMPERATURE).values
    assert daily.min() >= 0.0
    assert daily.max() <= 1.0


def test_pixel_with_no_valid_value_stays_nan():
    coarse = _composites([[np.nan, 0.5], [np.nan, 0.5]], ["2020-01-01", "2020-01-10"])
    daily = fapar(coarse, TEMPERATURE)
    assert np.isnan(daily.sel(pixel=0)).all()
    assert np.isfinite(daily.sel(pixel=1)).all()


def test_global_co2_reaches_every_pixel_on_the_daily_axis():
    record = xr.DataArray(
        [410.0, 412.0],
        dims=["time"],
        coords={"time": pd.to_datetime(["2020-01-01", "2020-01-11"])},
        attrs={"units": "ppm"},
    )
    daily = co2(record, TEMPERATURE)
    assert daily.dims == TEMPERATURE.dims
    np.testing.assert_array_equal(daily["time"].values, DATES.values)
    np.testing.assert_allclose(daily.sel(pixel=1).values, 410.0 + 0.2 * np.arange(10))


def test_template_time_dimension_need_not_be_called_time():
    template = TEMPERATURE.rename(time="t")
    coarse = _composites([[0.2, 0.2], [0.8, 0.8]], ["2020-01-03", "2020-01-06"])
    daily = fapar(coarse, template)
    assert daily.dims == ("t", "pixel")


def test_outputs_satisfy_their_daily_contracts():
    coarse = _composites([[0.2, 0.2], [0.8, 0.8]], ["2020-01-03", "2020-01-06"])
    with xra.enabled(True):
        assert fapar(coarse, TEMPERATURE).attrs["units"] == "1"
