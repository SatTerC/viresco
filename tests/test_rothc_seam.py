"""Tests for the RothC ``apply_ufunc`` pixel seam (``viresco.models.rothc._rothc``).

The contract is `seam.SeamContract`'s. The reference is an independent per-pixel
loop over rothc_py, on pixels with distinct soil parameters and climate, since a
single pixel cannot catch a misalignment.
"""

from typing import ClassVar

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from rothc_py import RothC, RothCParams, percent_modern_c
from seam import SeamContract

from viresco.models.rothc import (
    _ROTHC_OUTPUT_KEYS,
    _ROTHC_OUTPUT_NAMES,
    _rothc,
)

N_MONTHS = 24
N_PIXELS = 3
MONTHLY_DATES = pd.date_range("2020-01-01", periods=N_MONTHS, freq="ME")
PIXELS = np.arange(N_PIXELS)

# Per-pixel soil parameters — deliberately distinct so a mapping bug (e.g. all pixels
# getting pixel 0's clay) would change the outputs and fail the regression check.
CLAY = np.array([30.0, 15.0, 45.0])
DEPTH = np.array([25.0, 30.0, 20.0])
IOM = np.array([2.0, 1.0, 3.5])


def _temporal(base: np.ndarray) -> xr.DataArray:
    """A (time, pixel) DataArray whose columns differ per pixel."""
    return xr.DataArray(
        base,
        dims=["time", "pixel"],
        coords={"time": MONTHLY_DATES, "pixel": PIXELS},
    )


def _static(values: np.ndarray) -> xr.DataArray:
    return xr.DataArray(values, dims=["pixel"], coords={"pixel": PIXELS})


@pytest.fixture(scope="module")
def rothc_inputs() -> dict:
    """Heterogeneous multi-pixel inputs (distinct climate per pixel column)."""
    rng = np.random.default_rng(0)

    def _vary(center: float, spread: float) -> np.ndarray:
        # (time, pixel) with a per-pixel offset plus mild noise.
        offsets = np.linspace(-spread, spread, N_PIXELS)
        return (
            center
            + offsets[None, :]
            + rng.normal(0.0, spread / 4, (N_MONTHS, N_PIXELS))
        )

    return dict(
        temperature_monthly=_temporal(_vary(10.0, 4.0)),
        precipitation_monthly=_temporal(np.abs(_vary(50.0, 20.0))),
        potential_evapotranspiration_monthly=_temporal(np.abs(_vary(30.0, 10.0))),
        plant_cover_monthly=_temporal(np.ones((N_MONTHS, N_PIXELS), dtype=bool)),
        dpm_rpm_ratio_monthly=_temporal(np.full((N_MONTHS, N_PIXELS), 1.44)),
        soil_carbon_input_monthly=_temporal(np.abs(_vary(0.2, 0.1))),
        farmyard_manure_input_monthly=_temporal(np.zeros((N_MONTHS, N_PIXELS))),
        clay_content=_static(CLAY),
        soil_depth=_static(DEPTH),
        inert_organic_matter=_static(IOM),
        dates_monthly=MONTHLY_DATES,
        n_years_spinup=1,
    )


def _reference_loop(inputs: dict) -> dict[str, np.ndarray]:
    """Independent per-pixel reference, mirroring the pre-seam ``_rothc`` loop.

    Returns a dict of (time, pixel) numpy arrays, the anchor for the regression check.
    """
    n_spinup_months = inputs["n_years_spinup"] * 12
    start_date = inputs["dates_monthly"].to_pydatetime()[0]
    t_mod = percent_modern_c(start_date=start_date, n_months=N_MONTHS)

    def col(name: str, i: int) -> list:
        return inputs[name].values[:, i].tolist()

    per_pixel: list[dict] = []
    for i in range(N_PIXELS):
        params = RothCParams(
            clay=float(CLAY[i]), depth=float(DEPTH[i]), iom=float(IOM[i])
        )
        model = RothC(params)
        data = {
            "t_tmp": col("temperature_monthly", i),
            "t_rain": col("precipitation_monthly", i),
            "t_evap": col("potential_evapotranspiration_monthly", i),
            "t_PC": inputs["plant_cover_monthly"].values[:, i].astype(int).tolist(),
            "t_DPM_RPM": col("dpm_rpm_ratio_monthly", i),
            "t_C_Inp": col("soil_carbon_input_monthly", i),
            "t_FYM_Inp": col("farmyard_manure_input_monthly", i),
            "t_mod": t_mod,
        }
        spinup = {k: v[:n_spinup_months] for k, v in data.items()}
        _, outputs = model(data, spinup)  # type: ignore[reportArgumentType]
        per_pixel.append(outputs)

    return {
        name: np.column_stack([p[key] for p in per_pixel])
        for name, key in zip(_ROTHC_OUTPUT_NAMES, _ROTHC_OUTPUT_KEYS, strict=True)
    }


class TestRothCSeam(SeamContract):
    seam = staticmethod(_rothc)
    outputs = _ROTHC_OUTPUT_NAMES
    dates = MONTHLY_DATES
    # Distinct clay, depth and IOM must give distinct SOC.
    differs = "soil_organic_carbon_monthly"
    module = "viresco.models.rothc"
    node_config: ClassVar = {"n_years_spinup": 1}
    cached_output = "soil_organic_carbon_monthly"

    @pytest.fixture(scope="class")
    def seam_inputs(self, rothc_inputs):
        return rothc_inputs

    @pytest.fixture(scope="class")
    def reference(self, rothc_inputs):
        return _reference_loop(rothc_inputs)

    @pytest.fixture
    def node_inputs(self):
        def _mda(v: float) -> xr.DataArray:
            return xr.DataArray(
                np.full((N_MONTHS, N_PIXELS), float(v)),
                dims=["time", "pixel"],
                coords={"time": MONTHLY_DATES, "pixel": PIXELS},
            )

        return {
            "temperature_monthly": _mda(10.0),
            "precipitation_monthly": _mda(50.0),
            "potential_evapotranspiration_monthly": _mda(30.0),
            "soil_carbon_input_monthly": _mda(0.2),
            "clay_content": _static(CLAY),
            "soil_depth": _static(DEPTH),
            "inert_organic_matter": _static(IOM),
            "plant_type": _static(np.ones(N_PIXELS)),  # for the bridge helper nodes
            "latitude": _static(np.full(N_PIXELS, 51.5)),
        }
