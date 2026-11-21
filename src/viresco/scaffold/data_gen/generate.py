"""Generate synthetic input data for a viresco config.

Everything is generated at daily resolution — from the tables in
`viresco.scaffold.data_gen.daily` / `.static` where the variable has an entry,
and from a name-heuristic fallback otherwise — then aggregated to the coarser
files with `catena.transforms.resample`.

Generation is driven by `viresco.scaffold.data_gen.spec.Resolver`, which
memoises each variable and resolves dependencies between them on demand.

The units the config's modules declare for their inputs decide two things the
tables cannot: the units a fallback variable is labelled with, and whether a
coarser file holds a mean or a per-period total (`mm d-1` summed onto a monthly
`mm`).
"""

import dataclasses
from os import PathLike
from pathlib import Path

import xarray as xr
from catena import IOSpec, ParsedConfig
from catena.build import build_driver_from_config
from catena.formats import format_for
from catena.io import effective_suffix
from catena.transforms import resample
from xarray_annotated import declaration_from_hint

from ...temporal import offset
from ..config_gen import _accumulates
from .daily import DAILY_VARS
from .fallback import fallback_var
from .spec import (
    DEFAULT_LAT_RANGE,
    DEFAULT_LON_RANGE,
    DEFAULT_START_DATE,
    Grid,
    Resolver,
    Var,
)
from .static import STATIC_VARS


def _spec_vars(label: str, spec: "IOSpec | None") -> list[str]:
    """Return the file variable names an input section asks for.

    catena lets ``vars`` be omitted (bind everything in the file) or given as a
    ``{node = file_var}`` mapping. Generation runs before the file exists, so the
    omitted form has nothing to enumerate and is rejected here; the mapping form
    is read for its file-side names, which are what gets written.
    """
    if spec is None:
        return []
    if spec.vars is None:
        raise ValueError(
            f"[inputs.{label}] omits 'vars', so there is nothing to generate: "
            f"synthetic data is built from the variable list, and the file it "
            f"would otherwise be read from does not exist yet. List the "
            f"variables explicitly to generate this section."
        )
    if isinstance(spec.vars, dict):
        return list(spec.vars.values())
    return list(spec.vars)


def _node_names(label: str, spec: "IOSpec | None") -> dict[str, str]:
    """Map each file variable an input section asks for to its node name."""
    if spec is None or spec.vars is None:
        return {}
    if isinstance(spec.vars, dict):
        return {file_var: node for node, file_var in spec.vars.items()}
    suffix = effective_suffix(label, spec)
    return {var: f"{var}{suffix}" for var in spec.vars}


def _declared_units(config: ParsedConfig) -> dict[str, str]:
    """Return the unit each external input is declared with, by node name.

    Inputs no node declares a unit for are left out. The driver is built only to
    read its nodes' types, so the contract check is skipped: data that does not
    exist yet cannot be checked against them.
    """
    dr = build_driver_from_config(config, check_contracts=False)
    return {
        v.name: declared.unit.unit
        for v in dr.list_available_variables()
        if v.is_external_input
        and (declared := declaration_from_hint(v.type)) is not None
        and declared.unit is not None
    }


#: CF grid mapping for the synthetic grid, whose ``y`` and ``x`` are latitude and
#: longitude on WGS 84. Written by hand, so that writing it needs no geospatial
#: dependency.
_GRID_MAPPING = {
    "grid_mapping_name": "latitude_longitude",
    "semi_major_axis": 6378137.0,
    "inverse_flattening": 298.257223563,
    "longitude_of_prime_meridian": 0.0,
}


def _save_dataset_with_crs(ds: xr.Dataset, path: str | PathLike) -> None:
    """Save a dataset, with its CRS, in whichever format ``path``'s extension names.

    Dispatch is catena's: `catena.formats` is the one table of supported
    formats, and raises for any other extension. Each variable points at a CF
    grid-mapping variable, ``crs``, which is what catena's ``crs_equal`` input
    check compares.
    """
    p = Path(path)
    fmt = format_for(p)
    ds = ds.copy()
    for var in ds.data_vars.values():
        var.attrs["grid_mapping"] = "crs"
    ds["crs"] = xr.DataArray(0, attrs=_GRID_MAPPING)
    fmt.write(ds, p)


def generate_synthetic_data(
    config: ParsedConfig,
    grid: tuple[int, int],
    n_days: int,
    seed: int = 42,
    lat_range: tuple[float, float] = DEFAULT_LAT_RANGE,
    lon_range: tuple[float, float] = DEFAULT_LON_RANGE,
    start_date: str = DEFAULT_START_DATE,
) -> None:
    """Generate synthetic input data for every input section of a config.

    Parameters
    ----------
    config : ParsedConfig
        Parsed configuration from `catena.load_config`. Input paths in
        ``config.input_specs`` are used as the destinations for the generated
        files.
    grid : tuple[int, int]
        Grid dimensions as (n_lat, n_lon).
    n_days : int
        Number of days to generate.
    seed : int
        Random seed for reproducibility. Each variable draws from its own stream,
        derived from this seed and the variable's name, so its values do not
        depend on what else the config asked for.
    lat_range, lon_range : tuple[float, float]
        Bounding box, as ``(min, max)`` degrees. The temporal generators are
        written against latitude itself, so moving the box moves the climate with
        it — a tropical box really does come out warm and aseasonal.
    start_date : str
        ISO date of the first day.
    """
    n_lat, n_lon = grid

    daily_spec = config.input_specs.get("daily")
    weekly_spec = config.input_specs.get("weekly")
    monthly_spec = config.input_specs.get("monthly")
    static_spec = config.input_specs.get("static")

    daily_vars = set(_spec_vars("daily", daily_spec))
    weekly_vars = set(_spec_vars("weekly", weekly_spec))
    monthly_vars = set(_spec_vars("monthly", monthly_spec))
    static_vars = _spec_vars("static", static_spec)

    declared = _declared_units(config)
    nodes = {
        label: _node_names(label, spec)
        for label, spec in [
            ("daily", daily_spec),
            ("weekly", weekly_spec),
            ("monthly", monthly_spec),
            ("static", static_spec),
        ]
    }
    # A fallback variable takes its units from the finest section asking for it,
    # since that is the one it is generated at.
    fallback_units: dict[str, str] = {}
    for label in ("static", "monthly", "weekly", "daily"):
        for var, node in nodes[label].items():
            if node in declared:
                fallback_units[var] = declared[node]

    def _fallback(var: str) -> Var:
        generated = fallback_var(var)
        if var not in fallback_units:
            return generated
        return dataclasses.replace(generated, units=fallback_units[var])

    resolver = Resolver(
        grid=Grid(
            n_lat=n_lat,
            n_lon=n_lon,
            n_days=n_days,
            lat_range=lat_range,
            lon_range=lon_range,
            start_date=start_date,
        ),
        daily_vars=DAILY_VARS,
        static_vars=STATIC_VARS,
        fallback=_fallback,
        seed=seed,
    )

    def _at(var: str, label: str) -> xr.DataArray:
        # Everything temporal is produced daily and aggregated here, so a
        # variable that only ever appears in the weekly or monthly file is still
        # generated by a daily entry (or a fallback).
        source = resolver.daily(var)
        if label == "daily":
            return source
        target = declared.get(nodes[label].get(var, ""))
        if not _accumulates(source.attrs.get("units"), target):
            return resample(source, freq=offset(label))
        total = resample(source, freq=offset(label), aggfunc="sum")
        return total.assign_attrs(units=target)

    sections = [
        (daily_vars, daily_spec, "daily"),
        (weekly_vars, weekly_spec, "weekly"),
        (monthly_vars, monthly_spec, "monthly"),
    ]
    for names, spec, label in sections:
        if names and spec:
            ds = xr.merge([_at(v, label) for v in sorted(names)])
            _save_dataset_with_crs(ds, spec.path)

    if static_vars and static_spec:
        static_ds = xr.merge([resolver.static(v) for v in static_vars])
        _save_dataset_with_crs(static_ds, static_spec.path)
