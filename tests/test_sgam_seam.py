"""Tests for the SGAM ``apply_ufunc`` pixel seam (``viresco.models.sgam._sgam``).

The contract is `seam.SeamContract`'s. The reference is an independent per-pixel
loop over sgam, on pixels with distinct plant types, mixed-sign latitudes and
initial pools, since a single pixel cannot catch a misalignment.
"""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from seam import SeamContract

from viresco.models.sgam import (
    _SGAM_OUTPUT_NAMES,
    _build_pft_params_dataset,
    _pft_int_to_enum,
    _pft_params_from_dataset,
    _sgam,
)

N_WEEKS = 52
N_PIXELS = 3
WEEKLY_DATES = pd.date_range("2020-01-01", periods=N_WEEKS, freq="7D")
PIXELS = np.arange(N_PIXELS)

# Per-pixel metadata — deliberately distinct so a mapping bug (e.g. all pixels getting
# pixel 0's PFT or hemisphere) would change the outputs and fail the regression check.
PLANT_TYPE = np.array([0, 1, 3])  # tree, grass, crop -> distinct PftParams
LATITUDE = np.array([51.5, -33.0, 10.0])  # NH, SH, NH -> exercises hemisphere
LEAF_INIT = np.array([1.0, 2.0, 0.5])
STEM_INIT = np.array([5.0, 3.0, 1.0])
ROOT_INIT = np.array([2.0, 1.5, 0.8])


def _temporal(base: np.ndarray) -> xr.DataArray:
    """A (time, pixel) DataArray whose columns differ per pixel."""
    return xr.DataArray(
        base,
        dims=["time", "pixel"],
        coords={"time": WEEKLY_DATES, "pixel": PIXELS},
    )


def _static(values: np.ndarray) -> xr.DataArray:
    return xr.DataArray(values, dims=["pixel"], coords={"pixel": PIXELS})


@pytest.fixture(scope="module")
def sgam_inputs() -> dict:
    """Heterogeneous multi-pixel inputs (distinct climate per pixel column)."""
    rng = np.random.default_rng(0)

    def _vary(center: float, spread: float) -> np.ndarray:
        # (time, pixel) with a per-pixel offset plus mild noise.
        offsets = np.linspace(-spread, spread, N_PIXELS)
        return (
            center + offsets[None, :] + rng.normal(0.0, spread / 4, (N_WEEKS, N_PIXELS))
        )

    plant_type = _static(PLANT_TYPE.astype(float))
    return dict(
        plant_type=plant_type,
        pft_params=_build_pft_params_dataset(plant_type),
        temperature_weekly=_temporal(_vary(15.0, 5.0)),
        gpp_weekly=_temporal(np.abs(_vary(5.0, 2.0))),
        volumetric_water_content_weekly=_temporal(np.clip(_vary(0.3, 0.1), 0.0, 0.45)),
        vpd_weekly=_temporal(np.abs(_vary(1000.0, 300.0))),
        lue_weekly=_temporal(np.abs(_vary(2.0, 0.5))),
        iwue_weekly=_temporal(np.abs(_vary(100.0, 20.0))),
        dates_weekly=WEEKLY_DATES,
        disturbances_weekly=_temporal(np.zeros((N_WEEKS, N_PIXELS))),
        leaf_pool_init=_static(LEAF_INIT),
        stem_pool_init=_static(STEM_INIT),
        root_pool_init=_static(ROOT_INIT),
        latitude=_static(LATITUDE),
    )


def _reference_loop(inputs: dict) -> dict[str, np.ndarray]:
    """Independent per-pixel reference, mirroring the pre-seam ``_sgam`` loop.

    Returns a dict of (time, pixel) numpy arrays, the anchor for the regression check.
    """
    from sgam import Sgam

    week_of_year = inputs["dates_weekly"].isocalendar().week.values
    pft_params = inputs["pft_params"]

    def col(name: str, i: int) -> np.ndarray:
        return inputs[name].values[:, i]

    per_pixel: list[dict] = []
    for i in range(N_PIXELS):
        pft_enum = _pft_int_to_enum(int(inputs["plant_type"].values[i]))
        params = _pft_params_from_dataset(pft_params, (i,))
        hemisphere = "NH" if inputs["latitude"].values[i] >= 0 else "SH"

        output = Sgam(
            plant_type=pft_enum,
            pft_params=params,
            use_dynamic_allocation=True,
            hemisphere=hemisphere,
        )(
            gpp=col("gpp_weekly", i),
            temperature=col("temperature_weekly", i),
            soil_moisture=col("volumetric_water_content_weekly", i),
            vpd=col("vpd_weekly", i),
            lue=col("lue_weekly", i),
            iwue=col("iwue_weekly", i),
            week_of_year=week_of_year,
            disturbances=col("disturbances_weekly", i),
            leaf_pool_init=float(inputs["leaf_pool_init"].values[i]),
            stem_pool_init=float(inputs["stem_pool_init"].values[i]),
            root_pool_init=float(inputs["root_pool_init"].values[i]),
            litter_pool_init=0.0,
            removed_init=0.0,
            strict_mass_balance=False,
        )
        per_pixel.append(
            {
                "leaf_pool_weekly": output.pools.leaf,
                "stem_pool_weekly": output.pools.stem,
                "root_pool_weekly": output.pools.root,
                "litter_pool_weekly": output.pools.litter,
                "removed_pool_weekly": output.pools.removed,
                "npp_leaf_weekly": output.npp.leaf,
                "npp_stem_weekly": output.npp.stem,
                "npp_root_weekly": output.npp.root,
                "turnover_leaf_weekly": output.turnover.leaf,
                "turnover_stem_weekly": output.turnover.stem,
                "turnover_root_weekly": output.turnover.root,
                "respiration_leaf_weekly": output.respiration.leaf,
                "respiration_stem_weekly": output.respiration.stem,
                "respiration_root_weekly": output.respiration.root,
                "disturbance_leaf_weekly": output.disturbance.leaf,
                "disturbance_stem_weekly": output.disturbance.stem,
                "disturbance_root_weekly": output.disturbance.root,
                "cue_weekly": output.diagnostics.cue,
                "allocation_leaf_weekly": output.diagnostics.allocation_leaf,
                "allocation_stem_weekly": output.diagnostics.allocation_stem,
                "allocation_root_weekly": output.diagnostics.allocation_root,
                "drought_modifier_weekly": output.diagnostics.drought_modifier,
                "lue_score_weekly": output.diagnostics.lue_score,
                "iwue_score_weekly": output.diagnostics.iwue_score,
            }
        )

    return {
        name: np.column_stack([p[name] for p in per_pixel])
        for name in _SGAM_OUTPUT_NAMES
    }


class TestSGAMSeam(SeamContract):
    seam = staticmethod(_sgam)
    outputs = _SGAM_OUTPUT_NAMES
    dates = WEEKLY_DATES
    # Distinct PFTs and hemispheres must give distinct leaf pools.
    differs = "leaf_pool_weekly"
    module = "viresco.models.sgam"
    cached_output = "leaf_pool_weekly"

    @pytest.fixture(scope="class")
    def seam_inputs(self, sgam_inputs):
        return sgam_inputs

    @pytest.fixture(scope="class")
    def reference(self, sgam_inputs):
        return _reference_loop(sgam_inputs)

    @pytest.fixture
    def node_inputs(self):
        ones = np.ones((N_WEEKS, N_PIXELS))
        return {
            "plant_type": _static(PLANT_TYPE.astype(float)),  # drives pft_params
            "temperature_weekly": _temporal(ones * 15.0),
            "gpp_weekly": _temporal(ones * 5.0),
            "volumetric_water_content_weekly": _temporal(ones * 0.3),
            "vpd_weekly": _temporal(ones * 1000.0),
            "lue_weekly": _temporal(ones * 2.0),
            "iwue_weekly": _temporal(ones * 100.0),
            "disturbances_weekly": _temporal(ones * 0.0),
            "leaf_pool_init": _static(LEAF_INIT),
            "stem_pool_init": _static(STEM_INIT),
            "root_pool_init": _static(ROOT_INIT),
            "latitude": _static(LATITUDE),
        }
