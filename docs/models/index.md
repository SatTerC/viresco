---
title: Overview
icon: lucide/package
---

# Built-in models

`viresco` comes with the models below, which can be composed into a pipeline.
A model that carries state through time, or wraps an upstream package, is one node in the DAG, with helper nodes where its inputs need building.
A model without state whose science is written here, such as ACM, is a few nodes, each of which can be written out or replaced.

Viresco registers every model with catena, so a config names one by its section alone.

```toml
[splash]
soil_moisture_init_max_iter = 10
```


| Model | Description | Temporal resolution |
|-------|-------------|---------------------|
| [SPLASH](splash.md) | Semi-empirical water-balance model that computes actual evapotranspiration, soil moisture, and runoff from daily climate data | Daily |
| [P-model](pmodel.md) | Optimality-based photosynthesis model that computes gross primary production (GPP), light-use efficiency, intrinsic water-use efficiency, photosynthetic capacity (Vcmax, Jmax) and stomatal conductance from environmental drivers | Daily |
| [ACM](acm.md) | Aggregated Canopy Model: computes daily gross primary productivity from observed LAI, foliar nitrogen, temperature extremes, irradiance and CO2 | Daily |
| [SGAM](sgam.md) | Simplified Growth and Allocation Model: tracks carbon pools (leaf, stem, root, litter) over time | Weekly |
| [RothC](rothc.md) | Soil carbon decomposition model that simulates the turnover of organic matter in soil, producing soil organic carbon stocks | Monthly |

Each model runs at one temporal resolution, apart from a node that only that model uses.
There is one today, configured in its model's section: the daily disturbance detection whose weekly maximum SGAM consumes.

## Node names { #node-names }

Each node of a pipeline is named for the variable it holds, with a suffix for its temporal resolution:

| Resolution | Name | Example |
|------------|------|---------|
| Daily | bare | `temperature` |
| Weekly | `_weekly` | `temperature_weekly` |
| Monthly | `_monthly` | `temperature_monthly` |
| Static, with no time axis | bare | `elevation` |

Daily is the finest resolution Viresco models; sub-daily work belongs in a separate package.

This is a Viresco convention, not a catena one.
catena names an input `{var}{suffix}`, with the suffix defaulting to `_<section label>`, so a Viresco config sets `suffix = ""` on its `[inputs.daily]`, `[inputs.static]` and `[outputs.daily]` sections, and `from = ""` on each `[[resample]]` from daily.
`viresco setup` writes them that way.

Because daily and static names are both bare, a name alone does not say which a node is: its declared frequency does.



## Inputs on a grid { #inputs-on-a-grid }

The models take whatever dimensions their inputs have besides time: a grid `(y, x)`, a set of sites, or a single point.
catena passes each input on as its file holds it, and every cell is modelled independently.

`latitude` is an ordinary input, read from a file like any other.
`viresco data-gen` writes it as a variable.
A file that carries it as a coordinate binds it with the mapping form of `vars`:

| File | Binding |
|------|---------|
| A latitude-longitude grid | `vars = { latitude = "y" }` |
| A projected grid with a CF `lat` coordinate | `vars = { latitude = "lat" }` |
| A station file with a `lat` coordinate on `site` | `vars = { latitude = "lat" }` |

catena does not check that gridded inputs share a grid unless a config asks it to, and xarray's default inner join silently drops the cells that do not line up.
`viresco setup` therefore writes these checks over its input sections:

```toml
[validation]
checks = [
  { check = "crs_equal", inputs = ["daily", "static"] },
  { check = "coords_equal", inputs = ["daily", "static"], coords = ["y", "x"] },
]
```

Name only the gridded sections: `crs_equal` fails a file with no CRS, such as a table of sites.
See catena's [configuration reference][catena-validation] for the checks.

`[blocking]` and `[subset]` split one dimension of the inputs, `y` on a grid, so a block is a set of whole rows.

[catena-validation]: https://nerc-ceh.github.io/catena/reference/configuration.html#validation
