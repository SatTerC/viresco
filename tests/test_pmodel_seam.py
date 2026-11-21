"""Tests for the P-Model ``apply_ufunc`` block seam (``viresco.models.pmodel._pmodel``).

Unlike RothC/SGAM, the P-Model is a *whole-block* model: pyrealm vectorises over the
spatial axis internally, so there was never a per-pixel Python loop. The seam replaces a
bespoke ``xarray_io`` ``.data`` pull/repack with ``xr.apply_ufunc`` (no core dims, since
the model is element-wise), which keeps a future dask backend reachable.

The contract is `seam.SeamContract`'s. Because the P-Model is element-wise, the
reference runs pyrealm on each pixel column independently and stacks the results,
an independent calling pattern that catches any axis or coordinate mangling.

The contract runs over method variants that between them pass every
method-dependent input, climatological ones included, through the seam.
"""

import numpy as np
import pandas as pd
import pyrealm.pmodel
import pytest
import xarray as xr
from seam import SeamContract

from viresco.models.pmodel import _OUTPUT_ATTRIBUTES, _pmodel

N_DAYS = 52
N_PIXELS = 3
DATES = pd.date_range("2020-01-01", periods=N_DAYS, freq="D")
PIXELS = np.arange(N_PIXELS)

# Each variant names its methods and the extra inputs, by pyrealm name, they need.
VARIANTS = {
    "defaults": (
        dict(
            method_optchi="prentice14",
            method_jmaxlim="wang17",
            method_kphio="temperature",
            method_arrhenius="simple",
        ),
        (),
    ),
    "lavergne_sandoval_kattge_knorr": (
        dict(
            method_optchi="lavergne20_c3",
            method_jmaxlim="smith19",
            method_kphio="sandoval",
            method_arrhenius="kattge_knorr",
        ),
        ("theta", "aridity_index", "mean_growth_temperature"),
    ),
    "rootzonestress": (
        dict(
            method_optchi="prentice14_rootzonestress",
            method_jmaxlim="none",
            method_kphio="fixed",
            method_arrhenius="simple",
        ),
        ("rootzonestress",),
    ),
}


def _temporal(base: np.ndarray) -> xr.DataArray:
    """A (time, pixel) DataArray whose columns differ per pixel."""
    return xr.DataArray(
        base,
        dims=["time", "pixel"],
        coords={"time": DATES, "pixel": PIXELS},
    )


def _static(base: np.ndarray) -> xr.DataArray:
    """A climatological (pixel-only) DataArray, with no time axis."""
    return xr.DataArray(base, dims=["pixel"], coords={"pixel": PIXELS})


@pytest.fixture(scope="module", params=list(VARIANTS))
def pmodel_inputs(request) -> dict:
    """Heterogeneous multi-pixel inputs (distinct climate per pixel column)."""
    methods, extra_names = VARIANTS[request.param]
    rng = np.random.default_rng(0)

    def _vary(center: float, spread: float) -> np.ndarray:
        offsets = np.linspace(-spread, spread, N_PIXELS)
        return (
            center + offsets[None, :] + rng.normal(0.0, spread / 4, (N_DAYS, N_PIXELS))
        )

    extras = dict(
        theta=_temporal(np.clip(_vary(0.3, 0.1), 0.0, 0.8)),
        rootzonestress=_temporal(np.clip(_vary(0.7, 0.2), 0.0, 1.0)),
        mean_growth_temperature=_static(np.linspace(10.0, 20.0, N_PIXELS)),
        aridity_index=_static(np.linspace(0.3, 1.5, N_PIXELS)),
    )
    return dict(
        temperature=_temporal(_vary(15.0, 5.0)),
        vpd=_temporal(np.abs(_vary(1000.0, 300.0))),
        co2=_temporal(np.full((N_DAYS, N_PIXELS), 400.0)),
        pressure=_temporal(np.full((N_DAYS, N_PIXELS), 101325.0)),
        fapar=_temporal(np.clip(_vary(0.5, 0.2), 0, 1)),
        ppfd=_temporal(np.abs(_vary(500.0, 150.0))),
        extra_inputs={name: extras[name] for name in extra_names},
        **methods,
    )


def _reference_loop(inputs: dict) -> dict[str, np.ndarray]:
    """Independent per-pixel reference, exploiting the model's element-wise nature.

    Runs pyrealm column-by-column and stacks; this is the anchor for the regression
    check. For an element-wise model this must equal the whole-block seam result.
    """

    def col(name: str, i: int) -> np.ndarray:
        return inputs[name].values[:, i]

    # A climatological extra is repeated down the time axis, which is what
    # pyrealm needs and what the seam does for it.
    temperature = inputs["temperature"]
    extras = {
        name: da.broadcast_like(temperature).transpose("time", "pixel").values
        for name, da in inputs["extra_inputs"].items()
    }

    per_pixel: dict[str, list] = {name: [] for name in _OUTPUT_ATTRIBUTES}
    for i in range(N_PIXELS):
        env = pyrealm.pmodel.PModelEnvironment(
            tc=col("temperature", i),
            vpd=col("vpd", i),
            co2=col("co2", i),
            patm=col("pressure", i),
            fapar=col("fapar", i),
            ppfd=col("ppfd", i),
            **{name: values[:, i] for name, values in extras.items()},
        )
        model = pyrealm.pmodel.PModel(
            env=env,
            method_optchi=inputs["method_optchi"],
            method_kphio=inputs["method_kphio"],
            method_arrhenius=inputs["method_arrhenius"],
            method_jmaxlim=inputs["method_jmaxlim"],
        )
        for name, attribute in _OUTPUT_ATTRIBUTES.items():
            per_pixel[name].append(getattr(model, attribute))

    return {name: np.column_stack(cols) for name, cols in per_pixel.items()}


def _constant(v: float) -> xr.DataArray:
    return xr.DataArray(
        np.full((N_DAYS, N_PIXELS), float(v)),
        dims=["time", "pixel"],
        coords={"time": DATES, "pixel": PIXELS},
    )


def _drivers() -> dict[str, xr.DataArray]:
    return {
        "temperature": _constant(15.0),
        "vpd": _constant(1000.0),
        "co2": _constant(400.0),
        "pressure": _constant(101325.0),
        "fapar": _constant(0.5),
        "ppfd": _constant(500.0),
    }


class TestPModelSeam(SeamContract):
    seam = staticmethod(_pmodel)
    outputs = tuple(_OUTPUT_ATTRIBUTES)
    dates = DATES
    # Distinct climate columns must give distinct GPP.
    differs = "gpp_flux"
    module = "viresco.models.pmodel"
    cached_output = "gpp_flux"

    @pytest.fixture(scope="class")
    def seam_inputs(self, pmodel_inputs):
        return pmodel_inputs

    @pytest.fixture(scope="class")
    def reference(self, pmodel_inputs):
        return _reference_loop(pmodel_inputs)

    @pytest.fixture
    def node_inputs(self):
        return _drivers()


class TestExtraInputsReachTheCacheKey:
    def test_changing_an_extra_input_invalidates_the_cache(self, tmp_path):
        """An extra input reaches `pmodel`'s cache key through its `<axis>_inputs` node."""
        from catena import CacheSpec, build_driver

        spec = CacheSpec(path=str(tmp_path / "cache"))

        def run(theta: float) -> np.ndarray:
            dr = build_driver(
                ["viresco.models.pmodel"],
                {"method_optchi": "lavergne20_c3"},
                cache=spec,
            )
            result = dr.execute(  # type: ignore[reportArgumentType]
                ["gpp_flux"],
                inputs={**_drivers(), "volumetric_water_content": _constant(theta)},
            )
            return result["gpp_flux"].values

        dry = run(0.1)
        np.testing.assert_array_equal(run(0.1), dry)  # warm cache
        assert not np.allclose(run(0.4), dry)
