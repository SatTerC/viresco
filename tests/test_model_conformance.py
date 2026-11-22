"""Every registered module follows viresco's conventions for nodes.

The modules are read from `viresco.registry`, so a new model or node module is
checked as soon as it has an entry point, with nothing to add here. Two kinds of
check:

- **Static**, over the public functions of every model and node module: what a
  node's signature and docstring must declare, read without running anything.
- **A run on synthetic data**, for each model on its own: the config
  ``viresco setup`` would write, filled by ``viresco data-gen``, executed with
  every contract enforced, on a grid, on the same data stacked to sites, and with
  every dimension renamed. A model that runs only inside the four-model example
  pipeline, or only on ``(time, y, x)``, fails here.

The conventions themselves are in ``AGENTS.md``; the frequency rule has its own
test, `test_module_frequency`.
"""

import ast
import inspect
import re
import textwrap
import typing
from types import ModuleType

import numpy as np
import pytest
import toy_subpackage
import xarray as xr
import xarray_annotated as xra
from catena import get_final_vars, load_config, load_inputs
from conftest import RENAMED, driver_from_config, rename_dims, to_sites
from hamilton.graph_utils import find_functions
from xarray_annotated import declaration_from_hint, declarations_from_signature

from viresco.registry import DRIVERS, MODELS, import_registered
from viresco.scaffold.config_gen import generate_config
from viresco.scaffold.data_gen import generate_synthetic_data

#: The registered modules, and a test-only model written as a subpackage, whose
#: node lives in a submodule (see `toy_subpackage`).
MODULES: dict[str, ModuleType] = {
    **import_registered(MODELS),
    **import_registered(DRIVERS),
    "toy_subpackage": toy_subpackage,
}

#: Variables with no unit to declare, each with the reason.
UNITLESS = {
    "plant_type": "a category",
    "plant_cover_monthly": "a boolean mask",
    "latitude": "often bound from a coordinate that carries no units attribute",
}

#: Inputs read only for their time coordinate, as ``(node, parameter)``.
TIME_ONLY = {
    ("viresco.models.acm.acm_days_from_midsummer", "lai_obs"),
    ("viresco.models.rothc.plant_cover_monthly", "temperature_monthly"),
    ("viresco.models.rothc.dpm_rpm_ratio_monthly", "temperature_monthly"),
    ("viresco.models.rothc.farmyard_manure_input_monthly", "temperature_monthly"),
}

#: Set by `xarray_annotated.check_annotations` on what it wraps. Private to
#: xarray-annotated, which has no public way to ask.
_CHECKED = "_xarray_annotated_checked"


def _nodes() -> list[tuple[str, typing.Callable]]:
    """Every node function of a registered module, by qualified name.

    The node functions are Hamilton's, so a subpackage's include those its
    ``__init__.py`` imports from submodules.
    """
    return [
        (f"{module.__name__}.{name}", func)
        for module in MODULES.values()
        for name, func in find_functions(module)
    ]


NODE_FUNCS = _nodes()
NODE_IDS = [name for name, _ in NODE_FUNCS]


def test_nodes_in_a_subpackage_are_checked():
    """A larger model is a subpackage whose ``__init__.py`` exports its nodes."""
    assert "toy_subpackage.toy" in NODE_IDS


def _is_dataarray(hint: typing.Any) -> bool:
    if typing.get_origin(hint) is typing.Annotated:
        hint = typing.get_args(hint)[0]
    return hint is xr.DataArray


def _has_unit(hint: typing.Any) -> bool:
    declared = declaration_from_hint(hint)
    return declared is not None and declared.unit is not None


def _data_params(func) -> dict[str, inspect.Parameter]:
    return {
        name: p
        for name, p in inspect.signature(func).parameters.items()
        if p.kind is not inspect.Parameter.KEYWORD_ONLY
    }


def _settings(func) -> dict[str, inspect.Parameter]:
    return {
        name: p
        for name, p in inspect.signature(func).parameters.items()
        if p.kind is inspect.Parameter.KEYWORD_ONLY
    }


def _outputs(name: str, func) -> dict[str, typing.Any]:
    """Each node ``func`` produces, with its hint: one per field of a TypedDict."""
    returned = typing.get_type_hints(func, include_extras=True).get("return")
    if typing.is_typeddict(returned):
        return typing.get_type_hints(returned, include_extras=True)
    return {name.rsplit(".", 1)[-1]: returned}


def _doc_sections(func) -> dict[str, list[str]]:
    """Each numpydoc section's entry lines: the unindented lines under its rule."""
    lines = (inspect.getdoc(func) or "").splitlines()
    sections: dict[str, list[str]] = {}
    current = None
    for line, following in zip(lines, [*lines[1:], ""], strict=True):
        if re.fullmatch(r"-{3,}", following.strip()) and line.strip():
            current = sections.setdefault(line.strip(), [])
        elif (
            current is not None
            and line
            and not line[0].isspace()
            and not re.fullmatch(r"-{3,}", line)
        ):
            current.append(line)
    return sections


@pytest.mark.parametrize(("name", "func"), NODE_FUNCS, ids=NODE_IDS)
def test_data_inputs_declare_units(name, func):
    hints = typing.get_type_hints(func, include_extras=True)
    missing = [
        param
        for param in _data_params(func)
        if _is_dataarray(hints.get(param))
        and not _has_unit(hints[param])
        and param not in UNITLESS
        and (name, param) not in TIME_ONLY
    ]
    assert not missing, (
        f"{name}: no `Unit` on {missing}. Declare one (`Unit('1')` if "
        "dimensionless), or add the variable to UNITLESS with the reason."
    )


@pytest.mark.parametrize(("name", "func"), NODE_FUNCS, ids=NODE_IDS)
def test_outputs_declare_units(name, func):
    missing = [
        output
        for output, hint in _outputs(name, func).items()
        if _is_dataarray(hint) and not _has_unit(hint) and output not in UNITLESS
    ]
    assert not missing, f"{name}: no `Unit` on output {missing}"


@pytest.mark.parametrize(("name", "param"), sorted(TIME_ONLY))
def test_time_only_entries_are_needed(name, param):
    """Each entry names a parameter that exists and still declares no unit."""
    module, func_name = name.rsplit(".", 1)
    func = getattr(MODULES[module.rsplit(".", 1)[-1]], func_name, None)
    assert func is not None, f"{name} no longer exists"
    hint = typing.get_type_hints(func, include_extras=True).get(param)
    assert hint is not None, f"{name} no longer takes {param}"
    assert not _has_unit(hint), f"{name}:{param} declares a unit now; drop the entry"


@pytest.mark.parametrize(("name", "func"), NODE_FUNCS, ids=NODE_IDS)
def test_declaring_nodes_check_their_annotations(name, func):
    """A declaration nothing checks only documents the unit; it enforces nothing."""
    inputs, output = declarations_from_signature(func)
    if inputs or output:
        assert getattr(func, _CHECKED, False), (
            f"{name} declares contracts but is not wrapped in `check_annotations`"
        )


@pytest.mark.parametrize(("name", "func"), NODE_FUNCS, ids=NODE_IDS)
def test_settings_have_defaults(name, func):
    """`config_gen` writes a setting's default into the config it generates."""
    missing = [p for p, spec in _settings(func).items() if spec.default is spec.empty]
    assert not missing, f"{name}: keyword-only settings without a default: {missing}"


@pytest.mark.parametrize(("name", "func"), NODE_FUNCS, ids=NODE_IDS)
def test_docstring_splits_data_inputs_from_settings(name, func):
    """Data inputs under ``Parameters``, settings under ``Other Parameters``.

    A model page renders one node twice, once per section, so a setting under
    ``Parameters`` shows up among the model's data inputs.
    """
    sections = _doc_sections(func)
    for section, expected in [
        ("Parameters", _data_params(func)),
        ("Other Parameters", _settings(func)),
    ]:
        documented = [line.split(":")[0].strip() for line in sections.get(section, [])]
        assert sorted(documented) == sorted(expected), (
            f"{name}: `{section}` documents {sorted(documented)}, "
            f"the signature has {sorted(expected)}"
        )


@pytest.mark.parametrize(("name", "func"), NODE_FUNCS, ids=NODE_IDS)
def test_docstring_parameters_carry_no_type(name, func):
    """griffe renders a docstring type in place of the annotation, hiding units."""
    sections = _doc_sections(func)
    typed = [
        line
        for section in ("Parameters", "Other Parameters")
        for line in sections.get(section, [])
        if ":" in line
    ]
    assert not typed, f"{name}: write bare names, not `name : type`: {typed}"


def _typeddicts() -> list[tuple[str, type]]:
    found = {}
    for _, func in NODE_FUNCS:
        returned = typing.get_type_hints(func, include_extras=True).get("return")
        if returned is not None and typing.is_typeddict(returned):
            found[f"{returned.__module__}.{returned.__qualname__}"] = returned
    return sorted(found.items())


TYPEDDICTS = _typeddicts()


@pytest.mark.parametrize(("name", "cls"), TYPEDDICTS, ids=[n for n, _ in TYPEDDICTS])
def test_output_fields_have_docstrings(name, cls):
    """The model page's outputs table is the fields' docstrings."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    body = tree.body[0].body  # type: ignore[attr-defined]
    undocumented = [
        stmt.target.id
        for stmt, following in zip(body, [*body[1:], None], strict=True)
        if isinstance(stmt, ast.AnnAssign)
        and isinstance(stmt.target, ast.Name)
        and not (
            isinstance(following, ast.Expr)
            and isinstance(following.value, ast.Constant)
            and isinstance(following.value.value, str)
        )
    ]
    assert not undocumented, f"{name}: fields with no docstring: {undocumented}"


# --- Each model alone, on synthetic data ---

#: Two years: RothC spins up over one, and frequency inference needs timesteps.
GRID = (2, 2)
N_DAYS = 730

#: Placeholder file names for every section `generate_config` may write.
SECTIONS = [
    f"{kind}_{label}"
    for kind in ("inputs", "outputs")
    for label in ("daily", "weekly", "monthly", "static")
]


def _run(config, reshape=lambda da: da) -> dict[str, xr.DataArray]:
    inputs = {name: reshape(da) for name, da in load_inputs(config.input_specs).items()}
    final_vars: list = get_final_vars(config.output_specs)
    with xra.enabled(True):
        return driver_from_config(config).execute(final_vars, inputs=inputs)


@pytest.fixture(scope="module", params=sorted(import_registered(MODELS)))
def alone(request, tmp_path_factory):
    """One model's generated config and synthetic data, and its run on a grid."""
    model = request.param
    data_dir = tmp_path_factory.mktemp(f"alone_{model}")
    paths = {section: str(data_dir / f"{section}.nc") for section in SECTIONS}
    generate_config([model], [], paths).dump(data_dir / "config.toml")
    config = load_config(data_dir / "config.toml")
    generate_synthetic_data(config=config, grid=GRID, n_days=N_DAYS, seed=7)
    return config, _run(config)


def test_model_runs_alone_with_contracts_enforced(alone):
    config, results = alone
    assert set(results) == set(get_final_vars(config.output_specs))
    for name, result in results.items():
        assert {"y", "x"} <= set(result.dims), name


def test_model_runs_on_sites(alone):
    config, reference = alone
    sites = _run(config, to_sites)
    for name, expected in reference.items():
        assert sites[name].dims == to_sites(expected).dims, name
        np.testing.assert_array_equal(
            sites[name].values, to_sites(expected).values, err_msg=name
        )


def test_model_runs_on_any_dimension_names(alone):
    config, reference = alone
    renamed = _run(config, rename_dims)
    for name, expected in reference.items():
        actual = renamed[name]
        assert actual.dims == tuple(RENAMED.get(str(d), d) for d in expected.dims)
        np.testing.assert_array_equal(actual.values, expected.values, err_msg=name)
