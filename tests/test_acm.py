"""Tests for ACM (``viresco.models.acm``).

There is no upstream package to loop over, so the seam's reference is a scalar
transcription of Williams et al. (1997), eqs 2 and 4-9, evaluated one cell and day
at a time with `math`. The science is pinned to the paper's own predictions for
the Toolik Lake sites (Table 5 inputs, Fig. 3 outputs).
"""

import inspect
import math
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from seam import SeamContract

from viresco.models.acm import (
    _ACM_OUTPUT_NAMES,
    _W_M2_TO_MJ_M2_D,
    _acm,
    _acm_kernel,
    acm,
    days_from_midsummer,
)

N_DAYS = 365
N_PIXELS = 3
DAILY_DATES = pd.date_range("2021-01-01", periods=N_DAYS, freq="D")
PIXELS = np.arange(N_PIXELS)
LATITUDE = np.array([51.5, -33.0, 10.0])  # north, south, tropics

#: The paper's parameters and Harvard Forest site settings, without the prefix
#: the node's settings carry.
DEFAULTS = {
    name.removeprefix("acm_"): p.default
    for name, p in inspect.signature(acm).parameters.items()
    if p.kind is inspect.Parameter.KEYWORD_ONLY
}


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
        days_from_midsummer=days_from_midsummer(
            _static(LATITUDE), _temporal(np.zeros((N_DAYS, N_PIXELS)))
        ),
        **DEFAULTS,
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
    drivers = [
        inputs[name].transpose("time", "pixel").values
        for name in (
            "lai_obs",
            "max_temperature",
            "min_temperature",
            "shortwave_radiation",
            "co2",
            "days_from_midsummer",
        )
    ]
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
    seam = staticmethod(_acm)
    outputs = _ACM_OUTPUT_NAMES
    dates = DAILY_DATES
    differs = "gpp"
    module = "viresco.models.acm"
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
        names = ("lai_obs", "max_temperature", "min_temperature")
        return {
            **{name: acm_inputs[name] for name in names},
            "shortwave_radiation": acm_inputs["shortwave_radiation"],
            "co2": acm_inputs["co2"],
            "latitude": _static(LATITUDE),
        }


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


@pytest.mark.parametrize("site", TOOLIK)
def test_reproduces_toolik_lake(site):
    """Within 0.4 g m-2 d-1 of the paper's predictions at every Toolik site.

    The tolerance covers reading the figure and the one-decimal LAI of Table 5,
    which matters most at the lowest LAI, where GPP goes roughly as LAI squared.
    """
    lai, n, t, d_t, irradiance, doy, expected = TOOLIK[site]
    settings = DEFAULTS | {
        "foliar_nitrogen": n,
        "canopy_height": 0.5,
        "water_potential_difference": -2.5,
    }
    gpp, _ = _acm_kernel(
        np.array(lai),
        np.array(t + d_t),
        np.array(t - d_t),
        np.array(irradiance),
        np.array(355.0),
        np.array(abs(173.0 - doy)),
        **settings,
    )
    assert float(gpp) == pytest.approx(expected, abs=0.4)


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


def test_days_from_midsummer_declares_days(acm_inputs):
    assert acm_inputs["days_from_midsummer"].attrs["units"] == "d"


def test_irradiance_is_converted_from_watts():
    """150 W m-2 for a day is 12.96 MJ m-2."""
    assert pytest.approx(12.96) == 150.0 * _W_M2_TO_MJ_M2_D


def _one_cell(**overrides) -> dict:
    drivers = {
        "lai": np.array(3.0),
        "max_temperature": np.array(25.0),
        "min_temperature": np.array(15.0),
        "irradiance": np.array(20.0),
        "co2": np.array(400.0),
        "days_from_midsummer": np.array(20.0),
    } | {key: np.array(value) for key, value in overrides.items()}
    gpp, c_i = _acm_kernel(*drivers.values(), **DEFAULTS)
    return {"gpp": float(gpp), "internal_co2": float(c_i)}


def test_zero_lai_gives_zero_gpp_not_nan():
    result = _one_cell(lai=0.0)
    assert result["gpp"] == 0.0
    assert result["internal_co2"] == pytest.approx(400.0)


def test_masked_cell_stays_masked():
    assert math.isnan(_one_cell(lai=np.nan)["gpp"])


@pytest.mark.parametrize("driver", ["lai", "irradiance", "co2"])
def test_gpp_increases_with_driver(driver):
    base = _one_cell()["gpp"]
    more = {"lai": 4.0, "irradiance": 25.0, "co2": 600.0}[driver]
    assert _one_cell(**{driver: more})["gpp"] > base


def test_internal_co2_is_below_ambient():
    assert 0 < _one_cell()["internal_co2"] < 400.0


def test_positive_water_potential_difference_raises(acm_inputs):
    inputs = {
        name: acm_inputs[name]
        for name in (
            "lai_obs",
            "max_temperature",
            "min_temperature",
            "shortwave_radiation",
            "co2",
            "days_from_midsummer",
        )
    }
    with pytest.raises(ValueError, match="must be negative"):
        acm(**inputs, acm_water_potential_difference=0.5)
