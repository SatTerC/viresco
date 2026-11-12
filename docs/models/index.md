---
title: Overview
icon: lucide/package
---

# Built-in models

`viresco` currently comes with four models, which can be composed into a pipeline.
Each model is called through a single Python function, which becomes a node in the DAG.

Viresco registers all four with catena, so a config names one by its section alone.

```toml
[splash]
soil_moisture_init_max_iter = 10
```


| Model | Description | Temporal resolution |
|-------|-------------|---------------------|
| [SPLASH](splash.md) | Semi-empirical water-balance model that computes actual evapotranspiration, soil moisture, and runoff from daily climate data | Daily |
| [P-model](pmodel.md) | Optimality-based photosynthesis model that computes gross primary production (GPP), light-use efficiency, intrinsic water-use efficiency, photosynthetic capacity (Vcmax, Jmax) and stomatal conductance from environmental drivers | Weekly |
| [SGAM](sgam.md) | Simplified Growth and Allocation Model: tracks carbon pools (leaf, stem, root, litter) over time | Weekly |
| [RothC](rothc.md) | Soil carbon decomposition model that simulates the turnover of organic matter in soil, producing soil organic carbon stocks | Monthly |

Each model runs at one temporal resolution, apart from a node that only that model uses.
There are two today, both configured in their model's section: the mean growth temperature some P-model methods need, reduced from daily temperature, and the daily disturbance detection whose weekly maximum SGAM consumes.

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


