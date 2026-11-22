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
from hamilton.graph_utils import find_functions
from hamilton.settings import ENABLE_POWER_USER_MODE
from xarray_annotated import Declared, Freq, declaration_from_hint

from .. import temporal
from ..registry import COUPLINGS, DRIVERS, KINDS, MODELS, registered
from ..temporal import resample_offset
from .aggregations import aggfunc_for


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

    Node functions are Hamilton's `find_functions`, as for `get_model_config`.
    A model returns a TypedDict that `@extract_fields` splits into one node per
    field. That decorator does not carry the fields' `Annotated` metadata onto
    the resulting nodes, so the units are only reachable through the return
    annotation itself.
    """
    hints: dict[str, Any] = {}
    for name, func in find_functions(module):
        try:
            returned = typing.get_type_hints(func, include_extras=True).get("return")
        except (NameError, TypeError):
            continue
        if returned is None:
            continue
        if typing.is_typeddict(returned):
            hints.update(typing.get_type_hints(returned, include_extras=True))
        else:
            hints.setdefault(name, returned)
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
    """Return every module `viresco setup` offers: the models, then the drivers.

    Each list is sorted. Couplings are not offered: the generator selects them
    itself, wherever a chosen model supplies another's input under another name
    or in other units.
    """
    drivers = [name for name in registered(DRIVERS) if name not in NOT_OFFERED]
    return [*registered(MODELS), *drivers]


#: Registered modules `viresco setup` cannot write a working config for, each
#: with the reason. A config still enables one by naming its section.
NOT_OFFERED: dict[str, str] = {
    "interpolate": (
        "its coarse inputs take a series at any step coarser than daily, so they "
        "declare no frequency, and the generator cannot tell which input section "
        "they belong in"
    ),
}


def get_model_config(model_name: str) -> dict[str, Any]:
    """Collect a model's configurable settings and their defaults.

    Settings are the keyword-only arguments of the node that consumes them.
    Every node function is read, not just the model node: Hamilton's
    `find_functions`, which in a subpackage includes the nodes its
    ``__init__.py`` imports from submodules. Some settings sit off the model
    node: RothC's per-PFT DPM/RPM ratios are on
    `viresco.models.rothc.dpm_rpm_ratio_monthly`. The result is still one flat
    dict because catena merges a section's keys into one flat driver config
    regardless of which node consumes them.
    """
    module_path = _module_path(model_name)

    try:
        module = import_module(module_path)
    except ImportError:
        return {}

    settings: dict[str, Any] = {}
    for _, func in find_functions(module):
        settings.update(_settings_of(func))
    return settings


def _settings_of(func: Any) -> dict[str, Any]:
    """Return a node function's keyword-only settings and their defaults."""
    return {
        p.name: p.default
        for p in inspect.signature(func).parameters.values()
        if p.kind == inspect.Parameter.KEYWORD_ONLY
        and p.default is not inspect.Parameter.empty
        and p.default is not None  # TOML has no null; unset means default
    }


def _module_path(name: str) -> str:
    """Return the module registered under section ``name``, else ``name`` itself.

    A name no kind registers is taken to be a module path, as for a custom module.
    """
    for kind in KINDS:
        if (path := registered(kind).get(name)) is not None:
            return path
    return name


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


#: Coupling targets `viresco setup` never selects on its own. Each is a model's
#: estimate of a forcing that is better observed: SPLASH's PPFD is computed from
#: sunshine fraction, which measured radiation outdoes. A config can still set
#: the key by hand.
_MANUAL_COUPLINGS = frozenset({"ppfd"})


def _coupling_targets() -> dict[str, tuple[str, str, Freq | None]]:
    """Return each coupling function's target node, source and frequency.

    Keyed by function name, ``<target>__<source>``; the target's frequency is the
    one its return annotation declares, ``None`` for a static target.
    """
    module = import_module(COUPLINGS)
    targets: dict[str, tuple[str, str, Freq | None]] = {}
    for name, func in find_functions(module):
        target, _, source = name.partition("__")
        returned = typing.get_type_hints(func, include_extras=True).get("return")
        declaration = declaration_from_hint(returned)
        targets[name] = (
            target,
            source,
            None if declaration is None else declaration.freq,
        )
    return targets


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

    for model_name in model_names:
        module = import_module(_module_path(model_name))
        data_inputs, _, data_outputs = _analyze_model_module(
            module, base_config, declared
        )
        all_data_inputs.update(data_inputs)
        all_model_outputs.extend(data_outputs)

    # What each model *produces*, and at which frequency. A base may be produced
    # at one frequency and wanted at another, which is what decides below whether
    # it can be resampled or has to be loaded from a file.
    produced_at: dict[str, set[str | None]] = {}
    for output in all_model_outputs:
        produced_at.setdefault(_base(output), set()).add(_label(output))

    daily: set[str] = set()
    weekly: set[str] = set()
    monthly: set[str] = set()
    static: set[str] = set()
    # (base, source_label, target_label) for each coarsening, mapped to the
    # units the coarsened node is declared with.
    resamples: dict[tuple[str, str, str], str | None] = {}
    # Coarsenings of a rate onto a per-period total. See `_accumulates`.
    summed: set[tuple[str, str, str]] = set()
    # (base, target_label) for every coarsening: a variable derived like this
    # must not also be loaded.
    derived: set[tuple[str, str]] = set()

    def _record(base: str, source: str, target: str) -> None:
        """File one coarsening, with the units its output is declared with.

        The consumer's declaration wins. Where nothing consumes the coarsened
        node directly, a mean keeps the producer's units, so those are declared
        instead.
        """
        key = (base, source, target)
        source_units = _units(_node_name(base, source))
        target_units = _units(_node_name(base, target))
        derived.add((base, target))
        resamples[key] = target_units or source_units
        if _accumulates(source_units, target_units):
            # A rate wanted as a per-period total: summed, and relabelled with
            # the consumer's units, since a resample keeps its input's label.
            summed.add(key)

    def _unmet(name: str) -> bool:
        """Report whether no chosen module produces ``name``, even finer."""
        base, label = _base(name), _label(name)
        produced = produced_at.get(base, set())
        if label in produced:
            return False
        return label is None or _finest_source(produced, label) is None

    # Couplings: an input no chosen model produces, but one produces under
    # another name or in other units, is made from that model's output by the
    # coupling `<target>__<source>`, selected by `<target>_from = "<source>"`.
    # A coupling's own inputs may need loading or coupling in turn, so repeat
    # until nothing new is selected. See `viresco.couplings`.
    coupling_targets = _coupling_targets()
    coupling_module = import_module(COUPLINGS)
    couplings: dict[str, str] = {}
    while True:
        selected = False
        for name in sorted(all_data_inputs):
            if not _unmet(name):
                continue
            base, label = _base(name), _label(name)
            for target, source, freq in coupling_targets.values():
                key = f"{target}_from"
                target_label = _label_of(freq)
                if (
                    key in couplings
                    or target in _MANUAL_COUPLINGS
                    or source not in model_names
                    or _base_name(target, target_label) != base
                    or _finest_source({target_label}, label) is None
                ):
                    continue
                couplings[key] = source
                selected = True
                break
        if not selected:
            break
        data_inputs, _, data_outputs = _analyze_model_module(
            coupling_module, {**base_config, **couplings}, declared
        )
        all_data_inputs.update(data_inputs)
        for output in data_outputs:
            produced_at.setdefault(_base(output), set()).add(_label(output))

    by_label: dict[str | None, set[str]] = {
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
    }

    for name in sorted(all_data_inputs):
        base, label = _base(name), _label(name)

        produced = produced_at.get(base, set())
        if label in produced:
            # Produced at exactly the frequency wanted: nothing to load or do.
            continue

        source = _finest_source(produced, label)
        if source is not None and label is not None:
            # Produced finer than wanted, so coarsen it rather than loading it.
            _record(base, source, label)
            continue

        # Not produced at all, or only *coarser* than wanted. Resampling cannot
        # refine, so this has to come from a file even when a model does produce
        # the same name at a coarser frequency.
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

    # One entry per direction and aggregation, mean first since it is catena's
    # default and its entry omits `aggfunc`. A variable `scaffold.aggregations`
    # lists gets an entry of its own, and so does a rate summed into a total,
    # which also overwrites the label it kept.
    groups: dict[tuple[str, str, str, bool], dict[str, str | None]] = {}
    for key in sorted(resamples):
        base, source, target = key
        aggfunc = "sum" if key in summed else aggfunc_for(base)
        group = (source, target, aggfunc, key in summed)
        groups.setdefault(group, {})[base] = resamples[key]

    def _order(group: tuple[str, str, str, bool]) -> tuple[int, int, bool, str, bool]:
        source, target, aggfunc, overwrite = group
        return (
            _LABEL_ORDER.index(source),
            _LABEL_ORDER.index(target),
            aggfunc != "mean",
            aggfunc,
            overwrite,
        )

    resample_entries: list[dict[str, Any]] = []
    for group in sorted(groups, key=_order):
        source, target, aggfunc, overwrite = group
        units = {var: u for var, u in groups[group].items() if u is not None}
        resample_entries.append(
            {
                "vars": list(groups[group]),
                # `from` is a node-name suffix, and daily nodes have none.
                "from": "" if source in _BARE_LABELS else source,
                "to": target,
                "freq": resample_offset(source, target),
                **({} if aggfunc == "mean" else {"aggfunc": aggfunc}),
                **({"units": units} if units else {}),
                **({"overwrite_units": True} if overwrite else {}),
            }
        )

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
        "inputs_daily": sorted(inputs_daily),
        "inputs_weekly": sorted(inputs_weekly),
        "inputs_monthly": sorted(inputs_monthly),
        "inputs_static": sorted(static),
        "couplings": couplings,
        "resamples": resample_entries,
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

    # One flat section per model, named after the model. viresco registers each
    # model module under catena's `catena.modules` entry-point group (see
    # pyproject.toml), so the section name alone resolves it and no
    # `_import_path` is needed.
    for model in builtin_models:
        config_data[model] = dict(get_model_config(model))

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

    # catena does not check that gridded inputs share a grid unless asked, and
    # without the check xarray's default inner join silently drops the cells that
    # do not line up. Every section here is written on one grid by data-gen.
    gridded = list(config_data["inputs"])
    if len(gridded) > 1:
        config_data["validation"] = {
            "checks": [
                {"check": "crs_equal", "inputs": gridded},
                {"check": "coords_equal", "inputs": gridded, "coords": ["y", "x"]},
            ]
        }

    if required_data["couplings"]:
        config_data["couplings"] = dict(required_data["couplings"])
        coupling_funcs = dict(find_functions(import_module(COUPLINGS)))
        for key, source in required_data["couplings"].items():
            target = key.removesuffix("_from")
            config_data["couplings"].update(
                _settings_of(coupling_funcs[f"{target}__{source}"])
            )
    if required_data["resamples"]:
        config_data["resample"] = required_data["resamples"]

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

    _drop_repeated_settings(
        config_data,
        [*builtin_models, "couplings", *(m.rsplit(".", 1)[-1] for m in custom_modules)],
    )
    return Config(config_data)


def _drop_repeated_settings(config_data: dict[str, Any], sections: list[str]) -> None:
    """Keep each setting in the first section that declares it, in place.

    catena merges every section's keys into one flat config and raises on a key
    set in two sections. Two nodes in different modules may share a setting, as
    `viresco.drivers.radiation` and `viresco.couplings` share
    ``par_photons_per_mj``, and then one value serves both, so it is written
    once. Two different defaults for one name cannot both be honoured, so they
    raise.
    """
    first: dict[str, tuple[str, Any]] = {}
    for section in sections:
        settings = config_data.get(section)
        if not isinstance(settings, dict):
            continue
        for key in list(settings):
            if key.startswith("_"):
                continue
            if key not in first:
                first[key] = (section, settings[key])
                continue
            owner, value = first[key]
            if settings[key] != value:
                raise ValueError(
                    f"Setting {key!r} defaults to {value!r} in [{owner}] and to "
                    f"{settings[key]!r} in [{section}]; one config cannot set both."
                )
            del settings[key]
