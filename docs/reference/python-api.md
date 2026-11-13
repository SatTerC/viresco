---
title: Python API
icon: lucide/square-function
---

# Python API

Building and running a pipeline is catena's job, and viresco adds no wrapper around it.
Everything `viresco run` does is available from Python through [catena's API][catena-api]:

```python
import catena

report = catena.run("config.toml")
```

What viresco supplies is the modules that config points at, and the scaffolding for getting to a config in the first place.

## Models

A model module is a set of plain functions whose names are node names.
Catena imports the module named by a config section, so nothing here is normally called by hand, but the functions are ordinary and can be.

| Module | Model |
| --- | --- |
| [`viresco.models.splash`](modules/viresco.models/splash.md) | [SPLASH](../models/splash.md): daily water balance, evapotranspiration and runoff. |
| [`viresco.models.pmodel`](modules/viresco.models/pmodel.md) | [The P-model](../models/pmodel.md): daily photosynthesis, GPP and light-use efficiency. |
| [`viresco.models.sgam`](modules/viresco.models/sgam.md) | [SGAM](../models/sgam.md): weekly vegetation carbon pools and allocation. |
| [`viresco.models.rothc`](modules/viresco.models/rothc.md) | [RothC](../models/rothc.md): monthly soil carbon turnover. |

The [Models](../models/index.md) section covers the theory and the inputs and outputs of each.
These pages are the signatures.

## Nodes

Stand-alone nodes that belong to no single model, each module a catena module of its own.

| Module | Produces |
| --- | --- |
| [`viresco.nodes.humidity`](modules/viresco.nodes/humidity.md) | `vpd`, from dewpoint, specific humidity or relative humidity. |
| [`viresco.nodes.radiation`](modules/viresco.nodes/radiation.md) | `ppfd`, from shortwave radiation or SPLASH. |
| [`viresco.nodes.pressure`](modules/viresco.nodes/pressure.md) | `pressure`, from elevation. |
| [`viresco.nodes.interpolate`](modules/viresco.nodes/interpolate.md) | Daily `fapar` and `co2`, from coarser series. |

The [Input nodes](../nodes/index.md) page shows how a config uses them.

## Scaffolding

`viresco setup` and `viresco data-gen` are thin wrappers over the functions below, so a config and a set of synthetic inputs can be produced from a script or a notebook as easily as from the terminal.

| Name | Does |
| --- | --- |
| [`get_builtin_models`](modules/viresco.scaffold/config_gen.md#viresco.scaffold.config_gen.get_builtin_models) | The model names `viresco setup` offers. |
| [`get_model_config`](modules/viresco.scaffold/config_gen.md#viresco.scaffold.config_gen.get_model_config) | The settings one model accepts, with their defaults and descriptions. |
| [`generate_config`](modules/viresco.scaffold/config_gen.md#viresco.scaffold.config_gen.generate_config) | A runnable config for a chosen set of models, inputs and outputs wired up. |
| [`generate_synthetic_data`](modules/viresco.scaffold/data_gen/generate.md#viresco.scaffold.data_gen.generate.generate_synthetic_data) | Input files for every `[inputs.*]` section a config names. |

### Modules

| Module | Contents |
| --- | --- |
| [`viresco.scaffold.config_gen`](modules/viresco.scaffold/config_gen.md) | Reading a model's signatures to work out what it needs, and writing the TOML that supplies it. |
| [`viresco.scaffold.bridges`](modules/viresco.scaffold/bridges.md) | Producer/consumer pairs whose units disagree, and the factor between them. |
| [`viresco.scaffold.aggregations`](modules/viresco.scaffold/aggregations.md) | Variables coarsened by something other than a mean, and the aggregation they get instead. |
| [`viresco.scaffold.data_gen.generate`](modules/viresco.scaffold/data_gen/generate.md) | Config in, input files out. |
| [`viresco.scaffold.data_gen.spec`](modules/viresco.scaffold/data_gen/spec.md) | What a variable's generator is handed: the grid, the calendar, and the values already computed. |
| [`viresco.scaffold.data_gen.daily`](modules/viresco.scaffold/data_gen/daily.md) | The daily variables with a hand-written generator. |
| [`viresco.scaffold.data_gen.static`](modules/viresco.scaffold/data_gen/static.md) | The same for time-invariant variables. |
| [`viresco.scaffold.data_gen.fallback`](modules/viresco.scaffold/data_gen/fallback.md) | What a variable gets when no table entry names it: a kind inferred from the name, and noise to match. |

## Shared

| Module | Contents |
| --- | --- |
| [`viresco.temporal`](modules/viresco.temporal.md) | The temporal resolutions a pipeline speaks in, and the pandas offsets behind them. |

[catena-api]: https://nerc-ceh.github.io/catena/reference/python-api.html
