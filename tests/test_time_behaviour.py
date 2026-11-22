"""Each node's declared time behaviour is checked, not trusted.

`viresco.temporal.time_behaviour` declares a node ``pointwise`` (the default),
``record`` or ``stateful``. A declaration that is wrong misleads a user about
whether a result depends on when a run starts, so both ends are tested:

- the outputs of a chain of ``pointwise`` nodes are the same when the run starts
  half-way through the record, which catches a node that reads the whole record
  or carries state from its first steps, and the same, reordered, when the
  record runs backwards, which catches one that reads the step before, as a
  difference does. Cutting the end instead would catch neither: no step sees a
  later one;
- a ``stateful`` node says how its state is initialised, by a spin-up setting or
  an initial-state input.

See ``docs/adr/0003-component-kinds.md``.
"""

import inspect
import typing

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import xarray_annotated as xra
from catena import get_final_vars, load_config, load_inputs
from conftest import driver_from_config
from hamilton.graph_utils import find_functions

from viresco.registry import import_all
from viresco.scaffold.config_gen import generate_config, get_builtin_models
from viresco.scaffold.data_gen import generate_synthetic_data
from viresco.temporal import time_behaviour_of

#: Three years, so the second half still holds the full year SPLASH needs to
#: equilibrate its soil moisture.
N_DAYS = 3 * 365
SECTIONS = [
    f"{kind}_{label}"
    for kind in ("inputs", "outputs")
    for label in ("daily", "weekly", "monthly", "static")
]

#: Every node function of every registered module, by the function itself.
NODE_FUNCS = {
    func: f"{module.__name__}.{name}"
    for module in import_all().values()
    for name, func in find_functions(module)
}


def _second_half(inputs: dict[str, xr.DataArray]) -> dict[str, xr.DataArray]:
    """Every input from one date, the middle of the record, whatever its step."""
    times = [da["time"].values for da in inputs.values() if "time" in da.dims]
    start, end = min(t.min() for t in times), max(t.max() for t in times)
    # Whole weeks from the start, so a weekly resample of the daily inputs falls
    # on the same dates as the weekly inputs read from a file.
    week = np.timedelta64(7, "D")
    middle = start + ((end - start) // 2 // week) * week
    return {
        name: da.sel(time=slice(middle, None)) if "time" in da.dims else da
        for name, da in inputs.items()
    }


def _reversed(inputs: dict[str, xr.DataArray]) -> dict[str, xr.DataArray]:
    """Every input with its steps in reverse order, coordinates and all."""
    return {
        name: da.isel(time=slice(None, None, -1)) if "time" in da.dims else da
        for name, da in inputs.items()
    }


def _run(config, reshape=lambda inputs: inputs, final_vars=None, *, checked=True):
    inputs = reshape(load_inputs(config.input_specs))
    dr = driver_from_config(config)
    wanted: list = (
        get_final_vars(config.output_specs) if final_vars is None else final_vars
    )
    with xra.enabled(checked):
        return dr, dr.execute(wanted, inputs=inputs)


def _all_pointwise(dr, name: str) -> bool:
    """Report whether every node ``name`` depends on is a pointwise viresco node.

    A node built by catena, such as a ``[[resample]]``, has no viresco function
    behind it, and a resample is not pointwise, so it counts against.
    """
    upstream, _ = dr.graph.get_upstream_nodes([name])
    for node in upstream:
        if node.user_defined:
            continue  # data, loaded
        functions = [f for f in node.originating_functions or () if f in NODE_FUNCS]
        if not functions:
            return False
        if any(time_behaviour_of(f) != "pointwise" for f in functions):
            return False
    return True


@pytest.fixture(scope="module", params=get_builtin_models())
def runs(request, tmp_path_factory):
    """One module's generated pipeline, run whole and from half-way through."""
    module = request.param
    data_dir = tmp_path_factory.mktemp(f"time_{module}")
    paths = {section: str(data_dir / f"{section}.nc") for section in SECTIONS}
    generate_config([module], [], paths).dump(data_dir / "config.toml")
    config = load_config(data_dir / "config.toml")
    generate_synthetic_data(config=config, grid=(2, 2), n_days=N_DAYS, seed=7)
    dr, full = _run(config)
    pointwise = [name for name in full if _all_pointwise(dr, name)]
    if not pointwise:
        return full, {}, {}
    _, half = _run(config, _second_half, pointwise)
    # A frequency contract cannot hold on a record running backwards.
    _, backwards = _run(config, _reversed, pointwise, checked=False)
    return full, half, backwards


def _assert_pointwise(name, result, full, how):
    expected = full[name]
    if "time" in result.dims:
        expected = expected.sel(time=result["time"])
    np.testing.assert_allclose(
        result.values,
        expected.values,
        rtol=1e-12,
        err_msg=(
            f"{name} changes when the run {how}, but every node it depends on "
            "is pointwise; declare the one that reads other steps with "
            "@time_behaviour('record') or @time_behaviour('stateful')"
        ),
    )


def test_pointwise_chains_do_not_depend_on_the_period_run(runs):
    full, half, _ = runs
    for name, result in half.items():
        _assert_pointwise(name, result, full, "starts later")


def test_pointwise_chains_do_not_depend_on_the_order_of_steps(runs):
    full, _, backwards = runs
    for name, result in backwards.items():
        _assert_pointwise(name, result, full, "runs backwards")


def test_some_module_has_a_pointwise_chain():
    """Guards the test above against passing because it compares nothing."""
    module = "acm"
    assert module in get_builtin_models()
    acm = import_all()[module]
    assert all(time_behaviour_of(f) == "pointwise" for _, f in find_functions(acm))


STATEFUL = [
    (qualname, func)
    for func, qualname in NODE_FUNCS.items()
    if time_behaviour_of(func) == "stateful"
]


def test_the_models_that_carry_state_say_so():
    assert {name for name, _ in STATEFUL} >= {
        "viresco.models.splash.splash",
        "viresco.models.rothc.rothc",
        "viresco.models.sgam.sgam",
    }


@pytest.mark.parametrize(("name", "func"), STATEFUL, ids=[n for n, _ in STATEFUL])
def test_a_stateful_node_says_how_its_state_starts(name, func):
    """A spin-up setting, an initialisation method, or an initial-state input."""
    params = inspect.signature(func).parameters
    settings = {
        p for p, spec in params.items() if spec.kind is inspect.Parameter.KEYWORD_ONLY
    }
    inputs = set(params) - settings
    assert any(s.endswith(("_spinup_years", "_init_method")) for s in settings) or any(
        i.startswith("initial_") or i.endswith("_init") for i in inputs
    ), (
        f"{name} is stateful but takes no `<model>_spinup_years` setting and no "
        "`initial_<state>` input"
    )


# --- Couplings, which no single module's pipeline runs ---


def _synthetic(func, n_steps: int = 120) -> dict[str, xr.DataArray]:
    """Positive random inputs for ``func``, shaped by its declared frequencies."""
    rng = np.random.default_rng(3)
    inputs = {}
    for param, hint in typing.get_type_hints(func, include_extras=True).items():
        if param == "return":
            continue
        declared = xra.declaration_from_hint(hint)
        units = "1" if declared is None or declared.unit is None else declared.unit
        if declared is not None and declared.freq is not None:
            dates = pd.date_range(
                "2020-01-01", periods=n_steps, freq=declared.freq.freq
            )
            data = rng.uniform(1.0, 2.0, (n_steps, 2)).cumsum(axis=0)
            da = xr.DataArray(data, dims=["time", "pixel"], coords={"time": dates})
        else:
            da = xr.DataArray(rng.uniform(1.0, 2.0, 2), dims=["pixel"])
        inputs[param] = da.assign_attrs(units=str(units))
    return inputs


COUPLINGS = [
    (qualname, func)
    for func, qualname in NODE_FUNCS.items()
    if qualname.startswith("viresco.couplings.")
]


@pytest.mark.parametrize(("name", "func"), COUPLINGS, ids=[n for n, _ in COUPLINGS])
def test_a_pointwise_coupling_is_pointwise(name, func):
    """The same two checks as above, on each coupling called directly.

    A coupling that is not pointwise must fail at least one of them, so that an
    undeclared one fails here; one declared otherwise is skipped.
    """
    inputs = _synthetic(func)
    full = func(**inputs)

    def agrees(reshape) -> bool:
        try:
            result = func(**reshape(inputs))
        except ValueError:  # a resample, say, refuses a record running backwards
            return False
        if "time" not in result.dims:
            return False
        return bool(np.allclose(result.values, full.sel(time=result["time"]).values))

    holds = agrees(_second_half) and agrees(_reversed)
    if time_behaviour_of(func) == "pointwise":
        assert holds, f"{name} reads other steps; declare its time behaviour"
    else:
        assert not holds, (
            f"{name} is declared {time_behaviour_of(func)} but is pointwise"
        )
