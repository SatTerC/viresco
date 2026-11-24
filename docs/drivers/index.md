---
title: Drivers
icon: lucide/git-merge
---

# Drivers

A driver derives a forcing variable from what datasets distribute.
Its variants compute one quantity from different starting data, so the choice between them is set by the data you have, not by a scientific hypothesis; a choice of that kind is a [model](../models/index.md).
No driver consumes a model's output: one that would is a [coupling](../couplings.md).

Datasets seldom distribute a model's forcing daily in the units it takes.
fAPAR comes as 8- or 10-day composites, CO₂ as a monthly or annual record, humidity as dewpoint or specific humidity rather than VPD, and light as shortwave energy rather than a photon flux.

| Variable | Module | From | Key |
| --- | --- | --- | --- |
| [`vpd`](#humidity) | `humidity` | dewpoint temperature, specific humidity and pressure, or relative humidity | `vpd_from`: `dewpoint`, `specific_humidity`, `relative_humidity` |
| [`ppfd`](#radiation) | `radiation` | downwelling shortwave | `ppfd_from`: `shortwave`; `splash` selects the [coupling](../couplings.md) instead |
| [`pressure`](#pressure) | `pressure` | elevation | |
| [`fapar`, `co2`](#interpolate) | `interpolate` | composites or a record at any coarser step | |

Each module is a catena module of its own, registered under its name, so a pipeline enables one with a section of that name.
A pipeline either enables the module or loads the variable it produces, not both.
Where a module has variants, a config key chooses one, and an unset key chooses the first listed.
`viresco setup` offers every driver except `interpolate`, whose coarse inputs may arrive at any step and so declare no frequency for the generator to place them by.

```toml
[humidity]
vpd_from = "specific_humidity"

[radiation]

[pressure]

[interpolate]

# Composites and the CO2 record arrive coarser than daily. The suffix gives
# them the names the interpolate module expects: fapar_coarse, co2_coarse.
[inputs.weekly]
path = "inputs/composites.nc"
suffix = "_coarse"
vars = ["co2", "fapar"]
```

Units are checked where data enters each node, and are never converted silently.
ERA5 gives temperatures in kelvin and `ssrd` as accumulated joules, so convert those with [`xarray_annotated.units.convert`](https://jmarshrossney.github.io/xarray-annotated) or in the notebook that fetched them.

## Vapour pressure deficit { #humidity }

::: viresco.drivers.humidity.vpd__dewpoint
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.drivers.humidity.vpd__specific_humidity
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.drivers.humidity.vpd__relative_humidity
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

## Photosynthetic photon flux density { #radiation }

::: viresco.drivers.radiation.ppfd__shortwave
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

## Pressure { #pressure }

::: viresco.drivers.pressure.pressure
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

## Daily series from coarser ones { #interpolate }

Each series is interpolated linearly in time through its valid values, so a gap is bridged by the values either side.
Days outside the record take its first or last value, and a cell with no valid value stays NaN.

::: viresco.drivers.interpolate.fapar
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.drivers.interpolate.co2
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

## Python API

See the API documentation for [`humidity`](../reference/modules/viresco.drivers/humidity.md), [`radiation`](../reference/modules/viresco.drivers/radiation.md), [`pressure`](../reference/modules/viresco.drivers/pressure.md) and [`interpolate`](../reference/modules/viresco.drivers/interpolate.md).
