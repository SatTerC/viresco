---
title: Input nodes
icon: lucide/git-merge
---

# Input nodes

The P-model runs daily, but few datasets distribute its drivers daily in the units it takes.
fAPAR comes as 8- or 10-day composites, CO₂ as a monthly or annual record, humidity as dewpoint or specific humidity rather than VPD, and light as shortwave energy rather than a photon flux.
The modules of `viresco.nodes` build each driver from what datasets do distribute.

Each module is a catena module of its own, registered under its name, so a pipeline enables one with a section of that name.
A module produces the node the P-model consumes (`vpd`, `ppfd`, `pressure`, `fapar`, `co2`), so a pipeline either enables the module or loads that variable, not both.

```toml
[humidity]
vpd_from = "specific_humidity"

[radiation]
ppfd_from = "splash"

[pressure]

[interpolate]

# Composites and the CO2 record arrive coarser than daily. The suffix gives
# them the names the interpolate module expects: fapar_coarse, co2_coarse.
[inputs.weekly]
path = "inputs/composites.nc"
suffix = "_coarse"
vars = ["co2", "fapar"]
```

Where a module has variants, a config key chooses one, and an unset key chooses the first listed.

| Module | Produces | From | Key |
| --- | --- | --- | --- |
| [`humidity`](#humidity) | `vpd` | dewpoint temperature, specific humidity and pressure, or relative humidity | `vpd_from`: `dewpoint`, `specific_humidity`, `relative_humidity` |
| [`radiation`](#radiation) | `ppfd` | downwelling shortwave, or SPLASH's daily photon total | `ppfd_from`: `shortwave`, `splash` |
| [`pressure`](#pressure) | `pressure` | elevation | |
| [`interpolate`](#interpolate) | `fapar`, `co2` | composites or a record at any coarser step | |

Units are checked where data enters each node, and are never converted silently.
ERA5 gives temperatures in kelvin and `ssrd` as accumulated joules, so convert those with [`xarray_annotated.units.convert`](https://jmarshrossney.github.io/xarray-annotated) or in the notebook that fetched them.

## Humidity { #humidity }

::: viresco.nodes.humidity.vpd__dewpoint
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.nodes.humidity.vpd__specific_humidity
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.nodes.humidity.vpd__relative_humidity
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

## Radiation { #radiation }

::: viresco.nodes.radiation.ppfd__shortwave
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.nodes.radiation.ppfd__splash
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

## Pressure { #pressure }

::: viresco.nodes.pressure.pressure
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

## Interpolation { #interpolate }

Each series is interpolated linearly in time through its valid values, so a gap is bridged by the values either side.
Days outside the record take its first or last value, and a pixel with no valid value stays NaN.

::: viresco.nodes.interpolate.fapar
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.nodes.interpolate.co2
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      docstring_section_style: spacy

## Python API

See the API documentation for [`humidity`](../reference/modules/viresco.nodes/humidity.md), [`radiation`](../reference/modules/viresco.nodes/radiation.md), [`pressure`](../reference/modules/viresco.nodes/pressure.md) and [`interpolate`](../reference/modules/viresco.nodes/interpolate.md).
