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

Each model runs at one temporal resolution.
A node a model needs that runs at another lives in the `shared` module instead, which a config enables with a `[shared]` section.
Today that is the mean growth temperature some P-model methods need, reduced from daily temperature, and the daily disturbance detection whose weekly maximum SGAM consumes.
`viresco setup` adds the section whenever a chosen model needs it.


