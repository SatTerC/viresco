"""Tests for ACM (``viresco.models.acm``).

ACM is a set of stateless nodes, so its seam is their composition, run through a
catena driver (`seam.driver_seam`). There is no upstream package to loop over,
so the reference is a scalar transcription of Williams et al. (1997), eqs 2 and
4-9, evaluated one cell and day at a time with `math`. The science is pinned to
the paper's own predictions for the Toolik Lake sites (Table 5 inputs, Fig. 3
outputs).
"""

import inspect
import math
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from hamilton.graph_utils import find_functions
from seam import SeamContract, driver_seam

import viresco.models.acm as acm_module
from viresco.models.acm import (
    _W_M2_TO_MJ_M2_D,
    acm_canopy_conductance,
    days_from_midsummer,
)

MODULE = "viresco.models.acm"
OUTPUTS = ("gpp", "internal_co2")
run_acm = driver_seam(MODULE, OUTPUTS)

N_DAYS = 365
N_PIXELS = 3
DAILY_DATES = pd.date_range("2021-01-01", periods=N_DAYS, freq="D")
PIXELS = np.arange(N_PIXELS)
LATITUDE = np.array([51.5, -33.0, 10.0])  # north, south, tropics

#: Every node's settings and defaults: the paper's parameters and Harvard Forest.
SETTINGS = {
    name: p.default
    for _, func in find_functions(acm_module)
    for name, p in inspect.signature(func).parameters.items()
    if p.kind is inspect.Parameter.KEYWORD_ONLY
}
#: The same, without the prefix, as the scalar reference takes them.
DEFAULTS = {name.removeprefix("acm_"): value for name, value in SETTINGS.items()}


def _temporal(values: np.ndarray) -> xr.DataArray:
    return xr.DataArray(
        values, dims=["time", "pixel"], coords={"time": DAILY_DATES, "pixel": PIXELS}
    )


def _static(values: np.ndarray) -> xr.DataArray:
    return xr.DataArray(values, dims=["pixel"], coords={"pixel": PIXELS})


@pytest.fixture(scope="module")
def acm_inputs() -> dict:
    """Seasonal drivers whose columns differ, on ``(time, pixel)``."""
    rng = np.random.default_rng(0)
    season = np.sin(2 * np.pi * (np.arange(N_DAYS)[:, None] - 80) / 365)
    offsets = np.array([0.0, -2.0, 4.0])[None, :]
    temperature = 12.0 + 8.0 * season + offsets + rng.normal(0, 1.5, (N_DAYS, 3))
    half_range = rng.uniform(2.0, 6.0, (N_DAYS, N_PIXELS))
    return dict(
        lai_obs=_temporal(
            np.clip(3.0 + 2.0 * season + offsets / 4, 0.1, None)
            + rng.uniform(0, 0.2, (N_DAYS, N_PIXELS))
        ),
        max_temperature=_temporal(temperature + half_range),
        min_temperature=_temporal(temperature - half_range),
        shortwave_radiation=_temporal(
            np.clip(150.0 + 100.0 * season + 10 * offsets, 5.0, None)
            * rng.uniform(0.5, 1.0, (N_DAYS, N_PIXELS))
        ),
        co2=_temporal(np.full((N_DAYS, N_PIXELS), 415.0)),
        latitude=_static(LATITUDE),
    )


def _acm_scalar(
    lai, t_max, t_min, irradiance, c_a, d_ms, *, foliar_nitrogen, canopy_height,
    water_potential_difference, nue, nue_temperature_coefficient,
    co2_compensation_point, co2_half_saturation,
    conductance_temperature_coefficient, conductance_height_coefficient,
    max_quantum_yield, quantum_yield_lai_coefficient, day_length_coefficient,
    day_length_constant,
):  # fmt: skip
    """ACM for one cell and day, written out in the paper's symbols."""
    t = (t_max + t_min) / 2
    d_t = (t_max - t_min) / 2
    p_n = nue * foliar_nitrogen * lai * math.exp(nue_temperature_coefficient * t)
    g_c = (
        -water_potential_difference
        * math.exp(conductance_temperature_coefficient * t)
        / (conductance_height_coefficient * canopy_height + d_t)
    )
    theta, k = co2_compensation_point, co2_half_saturation
    q, p = theta - k, p_n / g_c
    c_i = 0.5 * (
        c_a + q - p + math.sqrt((c_a + q - p) ** 2 - 4 * (c_a * q - p * theta))
    )
    p_d = g_c * (c_a - c_i)
    e_0 = max_quantum_yield * lai**2 / (quantum_yield_lai_coefficient + lai**2)
    p_i = e_0 * irradiance * p_d / (e_0 * irradiance + p_d)
    return p_i * (day_length_coefficient * d_ms + day_length_constant), c_i


def _reference_loop(inputs: dict) -> dict[str, np.ndarray]:
    d_ms = days_from_midsummer(inputs["latitude"], inputs["lai_obs"])
    drivers = [
        inputs[name].transpose("time", "pixel").values
        for name in (
            "lai_obs",
            "max_temperature",
            "min_temperature",
            "shortwave_radiation",
            "co2",
        )
    ] + [d_ms.transpose("time", "pixel").values]
    drivers[3] = drivers[3] * 86400 / 1e6
    gpp = np.empty((N_DAYS, N_PIXELS))
    c_i = np.empty((N_DAYS, N_PIXELS))
    for t in range(N_DAYS):
        for i in range(N_PIXELS):
            gpp[t, i], c_i[t, i] = _acm_scalar(
                *(float(d[t, i]) for d in drivers), **DEFAULTS
            )
    return {"gpp": gpp, "internal_co2": c_i}


class TestAcmSeam(SeamContract):
    seam = staticmethod(run_acm)
    outputs = OUTPUTS
    dates = DAILY_DATES
    differs = "gpp"
    module = MODULE
    node_config: ClassVar = {}
    cached_output = "gpp"

    @pytest.fixture(scope="class")
    def seam_inputs(self, acm_inputs):
        return acm_inputs

    @pytest.fixture(scope="class")
    def reference(self, acm_inputs):
        return _reference_loop(acm_inputs)

    @pytest.fixture
    def node_inputs(self, acm_inputs):
        return acm_inputs


#: Toolik Lake, 1994 (Table 5): LAI, foliar N (g m-2), mean temperature and
#: half-range (degC), irradiance (MJ m-2 d-1), day of year; and the aggregated
#: model's GPP (g m-2 d-1) read off Fig. 3 to about 0.1.
TOOLIK = {
    "inlet control": (0.2, 3.3, 17.1, 5.7, 10.5, 200, 0.75),
    "inlet greenhouse": (0.4, 3.1, 19.8, 8.3, 8.7, 200, 1.6),
    "inlet N+P": (0.9, 4.0, 16.7, 5.8, 11.7, 200, 4.7),
    "outlet control": (0.3, 3.5, 11.3, 4.9, 13.9, 204, 1.15),
    "outlet greenhouse": (0.9, 2.7, 12.2, 4.9, 7.5, 204, 3.05),
    "outlet N+P": (1.7, 3.6, 11.0, 4.9, 14.3, 204, 7.45),
}
TOOLIK_LATITUDE = 68.63


@pytest.mark.parametrize("site", TOOLIK)
def test_reproduces_toolik_lake(site):
    """Within 0.4 g m-2 d-1 of the paper's predictions at every Toolik site.

    The tolerance covers reading the figure and the one-decimal LAI of Table 5,
    which matters most at the lowest LAI, where GPP goes roughly as LAI squared.
    """
    lai, n, t, d_t, irradiance, doy, expected = TOOLIK[site]
    date = pd.Timestamp("1994-01-01") + pd.Timedelta(days=doy - 1)

    def day(value: float) -> xr.DataArray:
        return xr.DataArray([value], dims=["time"], coords={"time": [date]})

    result = driver_seam(MODULE, ("gpp",))(
        lai_obs=day(lai),
        max_temperature=day(t + d_t),
        min_temperature=day(t - d_t),
        shortwave_radiation=day(irradiance / _W_M2_TO_MJ_M2_D),
        co2=day(355.0),
        latitude=xr.DataArray(TOOLIK_LATITUDE),
        acm_foliar_nitrogen=n,
        acm_canopy_height=0.5,
        acm_water_potential_difference=-2.5,
    )
    assert float(result["gpp"].item()) == pytest.approx(expected, abs=0.4)


def _days(latitude: float, dates: pd.DatetimeIndex) -> np.ndarray:
    lai = xr.DataArray(np.ones(len(dates)), dims=["time"], coords={"time": dates})
    return days_from_midsummer(xr.DataArray(latitude), lai).values


@pytest.mark.parametrize(
    ("latitude", "date", "expected"),
    [
        (51.5, "2021-06-22", 0.0),  # northern midsummer, day 173
        (51.5, "2021-07-22", 30.0),
        (51.5, "2021-12-31", 173.0),  # around the year end, not 192
        (-33.0, "2021-12-21", 0.0),  # southern midsummer, day 355
        (-33.0, "2021-01-20", 30.0),
        (-33.0, "2021-06-22", 182.0),
        (10.0, "2021-03-01", 80.0),  # tropics: constant
        (-23.0, "2021-12-21", 80.0),
    ],
)
def test_days_from_midsummer(latitude, date, expected):
    assert _days(latitude, pd.DatetimeIndex([date]))[0] == expected


def _one_cell(**overrides) -> dict[str, float]:
    drivers = {
        "lai_obs": 3.0,
        "max_temperature": 25.0,
        "min_temperature": 15.0,
        "shortwave_radiation": 230.0,
        "co2": 400.0,
    } | overrides
    date = pd.Timestamp("2021-06-01")
    inputs = {
        name: xr.DataArray([value], dims=["time"], coords={"time": [date]})
        for name, value in drivers.items()
    }
    result = run_acm(**inputs, latitude=xr.DataArray(51.5))
    return {name: float(da.item()) for name, da in result.items()}


def test_zero_lai_gives_zero_gpp_not_nan():
    result = _one_cell(lai_obs=0.0)
    assert result["gpp"] == 0.0
    assert result["internal_co2"] == pytest.approx(400.0)


def test_masked_cell_stays_masked():
    assert math.isnan(_one_cell(lai_obs=np.nan)["gpp"])


@pytest.mark.parametrize(
    ("driver", "more"),
    [("lai_obs", 4.0), ("shortwave_radiation", 300.0), ("co2", 600.0)],
)
def test_gpp_increases_with_driver(driver, more):
    assert _one_cell(**{driver: more})["gpp"] > _one_cell()["gpp"]


def test_internal_co2_is_below_ambient():
    assert 0 < _one_cell()["internal_co2"] < 400.0


def test_positive_water_potential_difference_raises(acm_inputs):
    with pytest.raises(ValueError, match="must be negative"):
        acm_canopy_conductance(
            acm_inputs["max_temperature"],
            acm_inputs["min_temperature"],
            acm_water_potential_difference=0.5,
        )
