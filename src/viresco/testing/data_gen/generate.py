"""Generate synthetic input data for a viresco config.

Everything is generated at daily resolution — from the tables in
`viresco.testing.data_gen.daily` / `.static` where the variable has an entry,
and from a name-heuristic fallback otherwise — then aggregated to the coarser
files with `catena.transforms.resample`.

Generation is driven by `viresco.testing.data_gen.spec.Resolver`, which
memoises each variable and resolves dependencies between them on demand.

What each variable is comes from the contracts its consumers declare, read with
`catena.scaffold.input_requirements`: its declared `Freq` says whether it is
daily, weekly, monthly or static, whatever its section is called. Only where no
consumer declares a frequency is the section's label read instead. Its declared
units decide two things the tables cannot: the units a fallback variable is
labelled with, and whether a coarser variable holds a mean or a per-period total
(`mm d-1` summed onto a monthly `mm`).
"""

import dataclasses
from os import PathLike
from pathlib import Path

import xarray as xr
from catena import ParsedConfig
from catena.formats import format_for
from catena.scaffold import InputRequirement, input_requirements
from catena.transforms import resample

from ...temporal import BY_LABEL, offset
from ..config_gen import _accumulates, _label_of
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

#: Resolutions ordered fine to coarse, so the finest one a variable is wanted at
#: can label its fallback.
_ORDER = ("daily", *(label for label in BY_LABEL if label != "daily"), "static")


def _resolution(file_var: str, requirement: InputRequirement, label: str) -> str:
    """Return the resolution a variable is wanted at: a `BY_LABEL` key or static.

    Read from the `Freq` its consumers declare. A variable none declares a
    frequency for, such as `viresco.drivers.interpolate`'s coarse inputs, which
    take a series at any step, is read from its section's label when that is a
    `BY_LABEL` key, and is static otherwise.
    """
    freqs = {d.freq for d in requirement.declared if d.freq is not None}
    if len(freqs) > 1:
        raise ValueError(
            f"{file_var!r} is declared at several frequencies by its consumers "
            f"({', '.join(map(repr, freqs))}), so it cannot be generated as one "
            f"variable."
        )
    if not freqs:
        return label if label in BY_LABEL else "static"
    return _label_of(freqs.pop()) or "static"


def _base_name(file_var: str, resolution: str) -> str:
    """Strip the suffix a coarser frequency carries, as viresco names its nodes.

    The tables hold each variable once, under its daily or static name, so a
    weekly ``temperature_weekly`` is generated from ``temperature``.
    """
    if resolution in ("daily", "static"):
        return file_var
    return file_var.removesuffix(f"_{resolution}")


def _declared_unit(requirement: InputRequirement) -> str | None:
    """Return the unit the first consumer declaring one gives, else ``None``."""
    return next((d.unit.unit for d in requirement.declared if d.unit is not None), None)


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
    p.parent.mkdir(parents=True, exist_ok=True)
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

    Each section's file is written to its configured path, holding the variables
    the section lists. A section may hold static variables beside time series of
    one frequency, but not time series of two: they would share a time axis.

    Parameters
    ----------
    config : ParsedConfig
        Parsed configuration from `catena.load_config`. Every input section must
        list its variables, since the files it would otherwise be read from do
        not exist yet.
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

    Raises
    ------
    ValueError
        If a section holds time series at two frequencies, or a variable's
        consumers declare it at two, or at a frequency viresco does not use.
    """
    n_lat, n_lon = grid
    requirements = input_requirements(config)

    wanted: dict[str, dict[str, tuple[str, str, InputRequirement]]] = {}
    for label, section in requirements.items():
        wanted[label] = {}
        for file_var, requirement in section.items():
            resolution = _resolution(file_var, requirement, label)
            base = _base_name(file_var, resolution)
            wanted[label][file_var] = (base, resolution, requirement)
        timed = {r for _, r, _ in wanted[label].values() if r != "static"}
        if len(timed) > 1:
            raise ValueError(
                f"Input section {label!r} holds variables at several frequencies "
                f"({', '.join(sorted(timed))}), which one file cannot hold on one "
                f"time axis. Split it into one section per frequency."
            )

    # A fallback variable takes its units from the finest resolution asking for
    # it, since that is the one it is generated at.
    fallback_units: dict[str, str] = {}
    for resolution in reversed(_ORDER):
        for section in wanted.values():
            for base, wanted_at, requirement in section.values():
                unit = _declared_unit(requirement)
                if wanted_at == resolution and unit is not None:
                    fallback_units[base] = unit

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

    def _at(base: str, resolution: str, target: str | None) -> xr.DataArray:
        # Everything temporal is produced daily and aggregated here, so a
        # variable that is only ever wanted weekly or monthly is still generated
        # by a daily entry (or a fallback).
        if resolution == "static":
            return resolver.static(base)
        source = resolver.daily(base)
        if resolution == "daily":
            return source
        if not _accumulates(source.attrs.get("units"), target):
            return resample(source, freq=offset(resolution))
        total = resample(source, freq=offset(resolution), aggfunc="sum")
        return total.assign_attrs(units=target)

    for label, section in wanted.items():
        if not section:
            continue
        arrays = [
            _at(base, resolution, _declared_unit(requirement)).rename(file_var)
            for file_var, (base, resolution, requirement) in sorted(section.items())
        ]
        _save_dataset_with_crs(xr.merge(arrays), config.input_specs[label].path)
