"""The tests every model's seam must pass, written once.

A model node maps a kernel over every cell with `xarray.apply_ufunc`, the seam.
A model built from stateless nodes has no such function: the composition of its
nodes is the seam, and `driver_seam` runs it. Each model's seam test subclasses
`SeamContract` and supplies what is particular to it: the seam function, its
outputs, and three fixtures.

``seam_inputs``
    Keyword arguments for the seam, on ``(time, pixel)`` with columns that
    differ, since a seam that mixes up cells passes on identical ones.
``reference``
    Each output as a ``(time, pixel)`` array computed independently of the
    seam, usually by a per-cell loop over the upstream package. This is the
    anchor for the regression check.
``node_inputs``
    Inputs for running the model's public node through a catena driver, for the
    caching check.

The contract is then:

1. The seam reproduces the reference, for every output.
2. Every output is ``(time, pixel)``, with the time coordinate reattached.
3. Distinct cells give distinct outputs.
4. Chunked (dask-backed) inputs give what eager ones do, so a dask backend
   stays open. Skipped without dask.
5. A cached run of the node matches an uncached one.

``output`` is parametrized over `SeamContract.outputs` by ``conftest``.
"""

from collections.abc import Callable
from typing import Any, ClassVar

import numpy as np
import pandas as pd
import pytest
import xarray as xr


def chunk_pixels(value: Any) -> Any:
    """Chunk every ``pixel``-bearing array in ``value`` one cell per chunk."""
    if isinstance(value, dict):
        return {key: chunk_pixels(v) for key, v in value.items()}
    if isinstance(value, xr.DataArray) and "pixel" in value.dims:
        return value.chunk({"pixel": 1})
    return value


def driver_seam(module: str, outputs: tuple[str, ...]) -> Callable[..., Any]:
    """Return a seam that runs ``module``'s nodes through a catena driver.

    For a model built from stateless nodes there is no ``apply_ufunc`` seam:
    the composition of its nodes is what maps the model over cells. The
    returned function takes the DAG's inputs as `xarray.DataArray` keyword
    arguments, and its settings as any other keyword arguments, and returns
    ``outputs``.
    """
    from catena import build_driver

    def run(**kwargs: Any) -> dict[str, xr.DataArray]:
        inputs = {k: v for k, v in kwargs.items() if isinstance(v, xr.DataArray)}
        config = {k: v for k, v in kwargs.items() if k not in inputs}
        return build_driver([module], config).execute(list(outputs), inputs=inputs)

    return run


class SeamContract:
    """Base class for a model's seam tests; see the module docstring."""

    #: The seam: `staticmethod` of the model's private mapped function.
    seam: ClassVar[Callable[..., Any]]
    #: Names of the seam's outputs. A seam returning one array names it here.
    outputs: ClassVar[tuple[str, ...]]
    #: The time coordinate of ``seam_inputs``.
    dates: ClassVar[pd.Index]
    #: An output whose columns must differ between neighbouring cells.
    differs: ClassVar[str]
    #: Tolerance for the chunked comparison. Loosen it only for a documented
    #: partition effect, such as SPLASH's spin-up convergence.
    chunk_rtol: ClassVar[float] = 1e-7

    #: The model's module path, its config, and the node output the caching
    #: check executes.
    module: ClassVar[str]
    node_config: ClassVar[dict[str, Any]] = {}
    cached_output: ClassVar[str]

    def _as_dict(self, result: Any) -> dict[str, xr.DataArray]:
        if isinstance(result, xr.DataArray):
            (name,) = self.outputs
            return {name: result}
        return result

    def _run_seam(self, inputs: dict) -> dict[str, xr.DataArray]:
        return self._as_dict(type(self).seam(**inputs))

    @pytest.fixture(scope="class")
    def seam_result(self, seam_inputs) -> dict[str, xr.DataArray]:
        return self._run_seam(seam_inputs)

    def test_matches_reference(self, seam_result, reference, output):
        np.testing.assert_allclose(
            seam_result[output].transpose("time", "pixel").values, reference[output]
        )

    def test_canonical_dims_and_coords(self, seam_result, reference):
        assert set(seam_result) == set(self.outputs)
        for name, da in seam_result.items():
            assert da.dims == ("time", "pixel"), name
            assert da.shape == reference[name].shape, name
            # apply_ufunc drops the time coord; the seam must reattach it.
            assert "pixel" in da.coords, name
            np.testing.assert_array_equal(
                da.coords["time"].values, self.dates.values, err_msg=name
            )

    def test_per_pixel_outputs_differ(self, seam_result):
        values = seam_result[self.differs].transpose("time", "pixel").values
        for left, right in zip(values.T, values.T[1:], strict=False):
            assert not np.allclose(left, right)

    def test_chunked_pixel_equivalence(self, seam_inputs, seam_result, output):
        pytest.importorskip("dask")
        chunked = self._run_seam(chunk_pixels(seam_inputs))
        np.testing.assert_allclose(
            chunked[output].compute().transpose("time", "pixel").values,
            seam_result[output].transpose("time", "pixel").values,
            rtol=self.chunk_rtol,
        )

    def test_cached_run_matches_uncached(self, tmp_path, node_inputs):
        from catena import CacheSpec, build_driver

        spec = CacheSpec(path=str(tmp_path / "cache"))

        def run(cache):
            dr = build_driver([self.module], self.node_config, cache=cache)
            result = dr.execute([self.cached_output], inputs=node_inputs)
            return result[self.cached_output].values

        uncached = run(None)
        run(spec)  # cold cache
        np.testing.assert_allclose(run(spec), uncached)  # warm cache
        assert (tmp_path / "cache").exists()
