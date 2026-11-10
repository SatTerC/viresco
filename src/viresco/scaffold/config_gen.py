"""Configuration generator for Viresco.

Generates a config file by introspecting the chosen model modules: which inputs
they need, at which frequencies, and which of those another model already
produces.
"""

import inspect
import typing
from importlib import import_module
from types import ModuleType
from typing import Any

import pint
import xarray as xr
from catena.config import Config
from hamilton import driver
from hamilton.settings import ENABLE_POWER_USER_MODE
from xarray_annotated import Declared, Freq, declaration_from_hint

from .. import models as model_modules
from .. import temporal
from ..temporal import resample_offset
from .bridges import Bridge, bridge_for


def _analyze_model_module(
    module: ModuleType,
    config: dict[str, Any],
    declared: dict[str, Declared] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Analyze a model module to discover its inputs and outputs.

    Parameters
    ----------
    module : ModuleType
        A Hamilton module (e.g., models.splash).
    config : dict[str, Any]
        Configuration dict with model parameters.

    Returns
    -------
    tuple
        A tuple containing three lists of strings:
        - 'data_inputs': list of external inputs of type xarray.DataArray
        - 'non_data_inputs': list of config inputs (not DataArray type)
        - 'data_outputs': list of produced outputs of type xarray.DataArray

    Each node's declaration is collected into ``declared`` as a side table, keyed
    by node name. Its `Freq` says which frequency the node runs at, and its unit
    tells a plain aggregation from a rate-to-total conversion.
    """
    dr = driver.Builder().with_modules(module).with_config(config).build()
    all_vars = dr.list_available_variables()
    declared = {} if declared is None else declared

    data_inputs = []
    data_outputs = []
    non_data_inputs = []

    # Inputs carry their declaration on the node type; outputs do not, because
    # `@extract_fields` drops the `Annotated` metadata when it splits a model's
    # return TypedDict into one node per field. Read those from the TypedDict.
    for name, hint in _output_hints(module).items():
        if (declaration := declaration_from_hint(hint)) is not None:
            declared.setdefault(name, declaration)

    for v in all_vars:
        if (declaration := declaration_from_hint(v.type)) is not None:
            declared.setdefault(v.name, declaration)
        # A declared node's type is ``Annotated[DataArray, ...]``; unwrap it so it
        # still counts as data.
        v_type = _unwrap_annotated(v.type)
        if v.is_external_input:
            if v_type == xr.DataArray:
                data_inputs.append(v.name)
            else:
                non_data_inputs.append(v.name)
        else:
            if v_type == xr.DataArray:
                data_outputs.append(v.name)

    return data_inputs, non_data_inputs, data_outputs


def _declared_unit(declaration: Declared | None) -> str | None:
    """Return the unit a declaration carries in a `Unit` marker, else ``None``."""
    if declaration is None or declaration.unit is None:
        return None
    return declaration.unit.unit


def _unwrap_annotated(hint: Any) -> Any:
    """Return the type inside an `Annotated` hint, else the hint itself."""
    if typing.get_origin(hint) is typing.Annotated:
        return typing.get_args(hint)[0]
    return hint


def _output_hints(module: ModuleType) -> dict[str, Any]:
    """Return each node function's declared output type, keyed by node name.

    A model returns a TypedDict that `@extract_fields` splits into one node per
    field. That decorator does not carry the fields' `Annotated` metadata onto
    the resulting nodes, so the units are only reachable through the return
    annotation itself.
    """
    hints: dict[str, Any] = {}
    for obj in vars(module).values():
        if not callable(obj) or getattr(obj, "__module__", None) != module.__name__:
            continue
        try:
            returned = typing.get_type_hints(obj, include_extras=True).get("return")
        except (NameError, TypeError):
            continue
        if returned is None:
            continue
        if typing.is_typeddict(returned):
            hints.update(typing.get_type_hints(returned, include_extras=True))
        else:
            hints.setdefault(getattr(obj, "__name__", ""), returned)
    return hints


def _label_of(freq: Freq | None) -> str | None:
    """Return the config label for a declared frequency, ``None`` for static.

    A node with no `Freq` has no time axis. Daily and static nodes both have bare
    names, so this, not the name, is what tells them apart.
    """
    if freq is None:
        return None
    for label, declared in temporal.BY_LABEL.items():
        if declared == freq:
            return label
    raise ValueError(
        f"{freq!r} is none of viresco's frequencies "
        f"({', '.join(f'{k}={v!r}' for k, v in temporal.BY_LABEL.items())})."
    )


def _node_name(base: str, label: str | None) -> str:
    """Return the node name for ``base`` at the frequency ``label``.

    Daily and static nodes are bare; coarser ones carry their label as a suffix.
    This is viresco's naming convention, not catena's.
    """
    return base if label in (None, "daily") else f"{base}_{label}"


def _base_name(name: str, label: str | None) -> str:
    """Invert `_node_name`: strip the suffix of a coarser frequency, if present."""
    return name if label in (None, "daily") else name.removesuffix(f"_{label}")


def get_builtin_models() -> list[str]:
    """Get list of builtin models."""
    from ..scaffold import BuiltinModels

    return [m.value for m in BuiltinModels]


def get_model_config(model_name: str) -> dict[str, Any]:
    """Collect a model's configurable settings and their defaults.

    Settings are the keyword-only arguments of the node that consumes them.
    Every public function the module defines is read, not just the model node,
    because some settings sit elsewhere: RothC's per-PFT DPM/RPM ratios are on
    `viresco.models.rothc.dpm_rpm_ratio_monthly`. The result is still one flat
    dict because catena merges a section's keys into one flat driver config
    regardless of which node consumes them.
    """
    module_path = (
        f"viresco.models.{model_name}"
        if model_name in model_modules.__all__
        else model_name
    )

    try:
        module = import_module(module_path)
    except ImportError:
        return {}

    settings: dict[str, Any] = {}
    for name, func in vars(module).items():
        if name.startswith("_") or not inspect.isfunction(func):
            continue
        if func.__module__ != module.__name__:
            continue
        settings.update(
            {
                p.name: p.default
                for p in inspect.signature(func).parameters.values()
                if p.kind == inspect.Parameter.KEYWORD_ONLY
                and p.default is not inspect.Parameter.empty
                and p.default is not None  # TOML has no null; unset means default
            }
        )
    return settings


#: Labels ordered fine to coarse, so an index comparison answers "can this be
#: resampled onto that?" — resampling only ever coarsens.
_LABEL_ORDER = tuple(temporal.BY_LABEL)


def _finest_source(produced: set[str | None], wanted: str | None) -> str | None:
    """Return the finest produced frequency that could supply ``wanted``.

    ``None`` when nothing produced can: either the base is not a model output at
    all, or every frequency it is produced at is coarser than what the consumer
    wants. Resampling coarsens only, so a coarser producer is no help.
    """
    if wanted not in _LABEL_ORDER:
        # Static: a producer at any frequency is a time series, not a constant.
        return wanted if wanted in produced else None
    candidates = [
        label
        for label in produced
        if label in _LABEL_ORDER
        and _LABEL_ORDER.index(label) <= _LABEL_ORDER.index(wanted)
    ]
    return min(candidates, key=_LABEL_ORDER.index) if candidates else None


def _accumulates(source_units: str | None, target_units: str | None) -> bool:
    """Report whether ``target_units`` is ``source_units`` accumulated over time.

    ``mm d-1`` coarsened onto ``mm`` is a *total*, not a mean: the consumer wants
    the rate integrated over the period. Deciding it from the declared units is
    what keeps this general — nothing here knows which variables are fluxes.

    Returns False when the two agree dimensionally (an ordinary mean) and when
    they are unrelated (a mismatch the contract check should report rather than
    this quietly papering over).
    """
    if not source_units or not target_units:
        return False
    try:
        registry = pint.get_application_registry()
        source = registry.Unit(source_units)
        target = registry.Unit(target_units)
    except (pint.UndefinedUnitError, TypeError, ValueError):
        return False
    if source.dimensionality == target.dimensionality:
        return False
    return (source * registry.Unit("day")).dimensionality == target.dimensionality


def _bridge_factor(
    bridge: Bridge, source_units: str | None, target_units: str | None
) -> float | None:
    """Return the multiplier taking ``source_units`` to ``target_units``.

    A bridge with an explicit ``factor`` uses it: those pairs are not
    dimensionally the same quantity, so no registry can derive them. Otherwise
    the two units are the same quantity written differently and pint knows the
    number — asking it keeps a conversion factor from being restated (and
    eventually mistyped) here.

    ``None`` where the declared units are missing or pint cannot relate them,
    which means the table has drifted from the models and the caller should not
    silently emit a wrong node.
    """
    if bridge.factor is not None:
        return bridge.factor
    if not source_units or not target_units:
        return None
    try:
        registry = pint.get_application_registry()
        return float(registry.Quantity(1.0, source_units).to(target_units).magnitude)
    except (pint.DimensionalityError, pint.UndefinedUnitError, TypeError, ValueError):
        return None


def _infer_required_data(model_names: list[str]) -> dict[str, Any]:
    """Infer required data using analyze_model_module.

    Uses data_inputs from each model to construct input lists,
    filters out model outputs, and determines resample lists.
    """
    base_config = {ENABLE_POWER_USER_MODE: True}

    # Collect all model inputs and outputs
    all_data_inputs: set[str] = set()
    all_model_outputs: list[str] = []
    declared: dict[str, Declared] = {}

    def _label(name: str) -> str | None:
        declaration = declared.get(name)
        return _label_of(None if declaration is None else declaration.freq)

    def _base(name: str) -> str:
        return _base_name(name, _label(name))

    def _units(name: str) -> str | None:
        return _declared_unit(declared.get(name))

    def _include(module_name: str) -> None:
        module = getattr(model_modules, module_name)
        data_inputs, _, data_outputs = _analyze_model_module(
            module, base_config, declared
        )
        all_data_inputs.update(data_inputs)
        all_model_outputs.extend(data_outputs)

    for model_name in model_names:
        _include(model_name)

    # The shared module belongs to no model, so it is pulled in only when a
    # chosen model consumes something it produces and no chosen model does.
    _, _, shared_outputs = _analyze_model_module(
        model_modules.shared, base_config, declared
    )
    shared_bases = {_base(name) for name in shared_outputs}
    wanted_bases = {_base(name) for name in all_data_inputs}
    model_output_bases = {_base(name) for name in all_model_outputs}
    modules = list(model_names)
    if (shared_bases & wanted_bases) - model_output_bases:
        _include("shared")
        modules.append("shared")

    # What each model *produces*, and at which frequency. A base may be produced
    # at one frequency and wanted at another, which is what decides below whether
    # it can be resampled or has to be loaded from a file.
    produced_at: dict[str, set[str | None]] = {}
    for output in all_model_outputs:
        produced_at.setdefault(_base(output), set()).add(_label(output))

    # Grid variables come from the grid module, not from files.
    grid_vars = {"latitude", "longitude"}

    daily: set[str] = set()
    weekly: set[str] = set()
    monthly: set[str] = set()
    static: set[str] = set()
    # (base, source_label, target_label) for each coarsening a consumer needs.
    resamples: set[tuple[str, str, str]] = set()
    # Coarsenings that also restate the units, so must be nodes rather than
    # `[[resample]]` entries. See `_accumulates`.
    accumulations: list[dict[str, Any]] = []
    # (base, target_label) for every coarsening, by either route: a variable
    # derived like this must not also be loaded.
    derived: set[tuple[str, str]] = set()
    # Units-restating nodes for producer/consumer pairs that disagree. Not a
    # coarsening, so tracked apart from `accumulations`. See `scaffold.bridges`.
    bridge_nodes: list[dict[str, Any]] = []

    def _record(base: str, source: str, target: str) -> None:
        """File one coarsening as either a resample or a units-restating node."""
        source_name = _node_name(base, source)
        target_name = _node_name(base, target)
        derived.add((base, target))
        if _accumulates(_units(source_name), _units(target_name)):
            # A rate wanted as a per-period total. `[[resample]]` preserves units,
            # so summing there would hand the consumer an `mm d-1` array still
            # labelled as such where it declares `mm`. A derive node can restate
            # them, so emit one of those instead.
            freq_offset = temporal.offset(target)
            accumulations.append(
                {
                    "name": target_name,
                    "inputs": [source_name],
                    "expression": (
                        f"{source_name}.resample(time='{freq_offset}').sum()"
                    ),
                    "units": _units(target_name),
                    "overwrite_units": True,
                    "freq": freq_offset,
                }
            )
        else:
            resamples.add((base, source, target))

    def _record_bridge(base: str, label: str | None) -> bool:
        """Emit the units-restating node for ``base``, if a bridge supplies it.

        False when no bridge covers this name, when its source is not produced
        at the frequency wanted, or when the factor cannot be established. In
        every case the caller falls through to loading the variable from a file.
        """
        bridge = bridge_for(base)
        if bridge is None or label not in produced_at.get(bridge.source, set()):
            return False
        source_name = _node_name(bridge.source, label)
        target_name = _node_name(base, label)
        target_units = _units(target_name)
        factor = _bridge_factor(bridge, _units(source_name), target_units)
        if factor is None or target_units is None:
            return False
        bridge_nodes.append(
            {
                "name": target_name,
                "inputs": [source_name],
                "expression": f"{source_name} * {factor:.6g}",
                "units": target_units,
                "overwrite_units": True,
                **({} if label is None else {"freq": temporal.offset(label)}),
            }
        )
        return True

    by_label: dict[str | None, set[str]] = {
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
    }

    for name in sorted(all_data_inputs):
        base, label = _base(name), _label(name)
        if base in grid_vars:
            continue

        produced = produced_at.get(base, set())
        if label in produced:
            # Produced at exactly the frequency wanted: nothing to load or do.
            continue

        source = _finest_source(produced, label)
        if source is not None and label is not None:
            # Produced finer than wanted, so coarsen it rather than loading it.
            _record(base, source, label)
            continue

        if _record_bridge(base, label):
            # Produced at this frequency under another name, in another model's
            # honest units. Convert it rather than loading a second copy.
            continue
        # Not produced at all, or only *coarser* than wanted. Resampling cannot
        # refine, so this has to come from a file even when a model does produce
        # the same name — pmodel's weekly `gpp` cannot supply sgam's daily one.
        by_label.get(label, static).add(base)

    # A variable loaded at a fine frequency and also wanted coarser is coarsened
    # rather than loaded twice. Priority: daily → weekly → monthly.
    for base in sorted(daily & weekly):
        _record(base, "daily", "weekly")
    for base in sorted(weekly & monthly):
        _record(base, "weekly", "monthly")
    for base in sorted((daily & monthly) - weekly):  # direct hop, no intermediate
        _record(base, "daily", "monthly")

    inputs_daily = daily - {b for b, t in derived if t == "daily"}
    inputs_weekly = weekly - {b for b, t in derived if t == "weekly"}
    inputs_monthly = monthly - {b for b, t in derived if t == "monthly"}

    def _pairs(source: str, target: str) -> list[str]:
        return sorted(b for b, s, t in resamples if s == source and t == target)

    resample_daily_to_weekly = _pairs("daily", "weekly")
    resample_daily_to_monthly = _pairs("daily", "monthly")
    resample_weekly_to_monthly = _pairs("weekly", "monthly")

    # Categorize model outputs for output file lists
    outputs_daily: list[str] = []
    outputs_weekly: list[str] = []
    outputs_monthly: list[str] = []

    by_output_label: dict[str | None, list[str]] = {
        "daily": outputs_daily,
        "weekly": outputs_weekly,
        "monthly": outputs_monthly,
    }
    for output in all_model_outputs:
        if (outputs := by_output_label.get(_label(output))) is not None:
            outputs.append(_base(output))

    return {
        "modules": modules,
        "inputs_daily": sorted(inputs_daily),
        "inputs_weekly": sorted(inputs_weekly),
        "inputs_monthly": sorted(inputs_monthly),
        "inputs_static": sorted(static),
        "bridges": bridge_nodes,
        "accumulations": accumulations,
        "resample_daily_to_weekly": resample_daily_to_weekly,
        "resample_daily_to_monthly": resample_daily_to_monthly,
        "resample_weekly_to_monthly": resample_weekly_to_monthly,
        "outputs_daily": sorted(set(outputs_daily)),
        "outputs_weekly": sorted(set(outputs_weekly)),
        "outputs_monthly": sorted(set(outputs_monthly)),
    }


#: Section labels whose variables have bare node names, so whose config sections
#: set ``suffix = ""``. See `_node_name`.
_BARE_LABELS = frozenset({"daily", "static"})


def generate_config(
    builtin_models: list[str],
    custom_modules: list[str],
    paths: dict[str, str],
) -> Config:
    """Generate a Config object.

    Parameters
    ----------
    builtin_models : list[str]
        List of builtin model names (e.g., ["splash", "pmodel"]).
    custom_modules : list[str]
        List of custom module paths.
    paths : dict[str, str]
        Dictionary mapping path keys to file paths.

    Returns
    -------
    Config
        Configuration object.
    """
    required_data = _infer_required_data(builtin_models)

    config_data: dict[str, Any] = {}

    # One flat section per module, named after the module: each chosen model,
    # plus `shared` when one of them needs it. viresco registers these under
    # catena's `catena.modules` entry-point group (see pyproject.toml), so the
    # section name alone resolves it and no `_import_path` is needed.
    for module in required_data["modules"]:
        config_data[module] = dict(get_model_config(module))

    # catena names each input node `{var}{suffix}`, with the suffix defaulting to
    # `_<section label>`. That is viresco's convention for the weekly and monthly
    # sections, but daily and static variables are consumed under bare names
    # (`temperature`, not `temperature_daily`), so those sections opt out of it.
    freq_keys = ("daily", "weekly", "monthly", "static")
    config_data["inputs"] = {
        freq: {
            "path": paths[f"inputs_{freq}"],
            "vars": required_data[f"inputs_{freq}"],
            **({"suffix": ""} if freq in _BARE_LABELS else {}),
        }
        for freq in freq_keys
        if required_data[f"inputs_{freq}"]
    }

    resample_list = []
    for k in (
        "resample_daily_to_weekly",
        "resample_daily_to_monthly",
        "resample_weekly_to_monthly",
    ):
        vars_ = required_data[k]
        if vars_:
            direction = k.removeprefix("resample_")
            from_freq, to_freq = direction.split("_to_")
            resample_list.append(
                {
                    "vars": vars_,
                    # `from` is a node-name suffix, and daily nodes have none.
                    "from": "" if from_freq in _BARE_LABELS else from_freq,
                    "to": to_freq,
                    "freq": resample_offset(from_freq, to_freq),
                    # aggfunc omitted → defaults to "mean" at parse time. A
                    # variable needing "sum" is a rate wanted as a total, and is
                    # emitted as a node instead — see `_accumulates`.
                }
            )

    # Nodes before resamples: a reader meets the derivations that change what a
    # variable *means* before the ones that only change its cadence.
    # Bridges first: a units restatement is the shorter story, and the reader
    # meets `gpp_weekly` before anything that consumes it.
    nodes = required_data["bridges"] + required_data["accumulations"]
    if nodes:
        config_data["node"] = nodes
    if resample_list:
        config_data["resample"] = resample_list

    output_freqs = ("daily", "weekly", "monthly")
    config_data["outputs"] = {
        freq: {
            "path": paths[f"outputs_{freq}"],
            "vars": required_data[f"outputs_{freq}"],
            **({"suffix": ""} if freq in _BARE_LABELS else {}),
        }
        for freq in output_freqs
        if required_data[f"outputs_{freq}"]
    }

    for mod_path in custom_modules:
        # A module catena has no registration for still needs an explicit
        # `_import_path`, which makes the section label free-form. Use the
        # module's own last component so the config reads naturally.
        label = mod_path.rsplit(".", 1)[-1]
        config_data[label] = {
            "_import_path": mod_path,
            **get_model_config(mod_path),
        }

    return Config(config_data)
