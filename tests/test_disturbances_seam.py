"""Tests for the disturbance-detection ``apply_ufunc`` block seam
(``viresco.models.sgam._disturbances``).

``sgam.Disturbances.forward`` is a *whole-block* computation: it diffs GPP/LAI along the
time axis and is otherwise element-wise over pixels, so it vectorises over ``pixel``
exactly like SPLASH. The seam replaces a bespoke ``xarray_io`` ``.data`` pull with
``xr.apply_ufunc`` (``time`` the core dim, ``pixel`` the broadcast dim,
``vectorize=False`` so the kernel still vectorises the whole block), retiring the last
use of ``xarray_io``.

``disturbance_threshold`` is per-PFT and therefore per-pixel: it enters the block as a
``(pixel,)`` array that broadcasts inside ``Disturbances.forward``. The reference below
is deliberately built the *other* way -- one scalar-threshold ``Disturbances`` call per
pixel column -- so it is an independent check that the broadcast is doing what a
per-pixel loop would.

The contract is `seam.SeamContract`'s. On top of it, a per-PFT threshold must bite:
a moderate decline that exceeds the crop threshold but not the grass or tree ones
is flagged only on the crop pixel.
"""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from seam import SeamContract
from sgam import Disturbances
from sgam.pft import PlantFunctionalType, get_default_pft_params

from viresco.models.sgam import _disturbances, pft_params

N_DAYS = 120
N_PIXELS = 3
DAILY_DATES = pd.date_range("2020-01-01", periods=N_DAYS, freq="D")
PIXELS = np.arange(N_PIXELS)

# One pixel per PFT of interest: tree (threshold 0.3), crop (0.1), grass (0.2).
PLANT_TYPES = np.array([0, 3, 1])
TREE_PX, CROP_PX, GRASS_PX = 0, 1, 2

# A disturbance fires when, on a warm day, GPP and LAI both drop by more than the
# pixel's PFT threshold. Put a large drop on a *different* day per pixel so columns
# differ, then one shared moderate drop that only the crop threshold catches.
DROP_DAYS = np.array([40, 60, 80])
BIG_DROP = 0.2  # 80% decline -- above every PFT threshold
MODERATE_DROP_DAY = 100
MODERATE_DROP = 0.85  # 15% decline -- above crop (0.1), below grass (0.2)/tree (0.3)
GROWING_SEASON_LIMIT = 10.0


def _build_climate() -> dict[str, np.ndarray]:
    """Warm, smooth climate with one sharp GPP+LAI crash per pixel (distinct days),
    plus a shared moderate decline that only a crop-threshold pixel should flag."""
    temperature = np.full((N_DAYS, N_PIXELS), 20.0)  # always above growing-season limit
    gpp = np.full((N_DAYS, N_PIXELS), 5.0)
    lai = np.full((N_DAYS, N_PIXELS), 2.0)
    for p, day in enumerate(DROP_DAYS):
        gpp[day:, p] *= BIG_DROP
        lai[day:, p] *= BIG_DROP
    gpp[MODERATE_DROP_DAY:, :] *= MODERATE_DROP
    lai[MODERATE_DROP_DAY:, :] *= MODERATE_DROP
    return {"temperature": temperature, "gpp": gpp, "lai": lai}


def _temporal(base: np.ndarray) -> xr.DataArray:
    return xr.DataArray(
        base,
        dims=["time", "pixel"],
        coords={"time": DAILY_DATES, "pixel": PIXELS},
    )


def _static(values: np.ndarray) -> xr.DataArray:
    return xr.DataArray(values, dims=["pixel"], coords={"pixel": PIXELS})


@pytest.fixture(scope="module")
def disturbance_inputs() -> dict:
    climate = _build_climate()
    return dict(
        temperature=_temporal(climate["temperature"]),
        gpp_obs=_temporal(climate["gpp"]),
        lai_obs=_temporal(climate["lai"]),
        disturbance_threshold=pft_params(_static(PLANT_TYPES))["disturbance_threshold"],
        growing_season_limit=GROWING_SEASON_LIMIT,
    )


def _reference_block(inputs: dict) -> np.ndarray:
    """Independent per-pixel reference: one scalar-threshold ``Disturbances`` call per
    column, with the threshold looked up straight from the sgam PFT defaults."""
    members = list(PlantFunctionalType)
    columns = []
    for p, pft_int in enumerate(PLANT_TYPES):
        threshold = get_default_pft_params(members[int(pft_int)]).disturbance_threshold
        detector = Disturbances(
            growing_season_limit=GROWING_SEASON_LIMIT,
            disturbance_threshold=threshold,
        )
        columns.append(
            detector.forward(
                inputs["temperature"].values[:, p],
                inputs["gpp_obs"].values[:, p],
                inputs["lai_obs"].values[:, p],
                aggregate=False,
            )
        )
    return np.stack(columns, axis=1)


class TestDisturbancesSeam(SeamContract):
    seam = staticmethod(_disturbances)
    outputs = ("disturbances",)
    dates = DAILY_DATES
    # The crash is on a different day per pixel.
    differs = "disturbances"
    module = "viresco.models.sgam"
    cached_output = "disturbances"

    @pytest.fixture(scope="class")
    def seam_inputs(self, disturbance_inputs):
        return disturbance_inputs

    @pytest.fixture(scope="class")
    def reference(self, disturbance_inputs):
        return {"disturbances": _reference_block(disturbance_inputs)}

    @pytest.fixture
    def node_inputs(self, disturbance_inputs):
        # disturbances depends on the pft_params node, built from plant_type.
        inputs = {
            key: val
            for key, val in disturbance_inputs.items()
            if key not in ("disturbance_threshold", "growing_season_limit")
        }
        return {**inputs, "plant_type": _static(PLANT_TYPES)}


class TestPerPixelDetection:
    @pytest.fixture(scope="class")
    def severity(self, disturbance_inputs) -> np.ndarray:
        return _disturbances(**disturbance_inputs).transpose("time", "pixel").values

    def test_each_pixel_is_disturbed_on_its_drop_day(self, severity):
        for p, day in enumerate(DROP_DAYS):
            assert severity[day, p] > 0.0

    def test_thresholds_are_per_pft(self, severity):
        # The shared 15% decline is above the crop threshold (0.1) but below the
        # grass (0.2) and tree (0.3) ones, so only the crop pixel flags it. A
        # single hardcoded threshold could not produce this pattern.
        assert severity[MODERATE_DROP_DAY, CROP_PX] > 0.0
        assert severity[MODERATE_DROP_DAY, GRASS_PX] == 0.0
        assert severity[MODERATE_DROP_DAY, TREE_PX] == 0.0
        # Over the whole record the crop pixel registers strictly more events.
        n_events = (severity > 0.0).sum(axis=0)
        assert n_events[CROP_PX] > n_events[GRASS_PX] == n_events[TREE_PX]
