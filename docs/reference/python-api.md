---
title: Python API
icon: lucide/square-function
---

# Python API

Building and running a pipeline is catena's job, and viresco adds no wrapper around it.
Everything `catena run` does is available from Python through [catena's API][catena-api]:

```python
import catena

report = catena.run("config.toml")
```

What viresco supplies is the modules that config points at.

## Models

A model module is a set of plain functions whose names are node names.
Catena imports the module named by a config section, so nothing here is normally called by hand, but the functions are ordinary and can be.

| Module | Model |
| --- | --- |
| [`viresco.models.splash`](modules/viresco.models/splash.md) | [SPLASH](../models/splash.md): daily water balance, evapotranspiration and runoff. |
| [`viresco.models.pmodel`](modules/viresco.models/pmodel.md) | [The P-model](../models/pmodel.md): daily photosynthesis, GPP and light-use efficiency. |
| [`viresco.models.acm`](modules/viresco.models/acm.md) | [ACM](../models/acm.md): daily gross primary productivity. |
| [`viresco.models.sgam`](modules/viresco.models/sgam.md) | [SGAM](../models/sgam.md): weekly vegetation carbon pools and allocation. |
| [`viresco.models.rothc`](modules/viresco.models/rothc.md) | [RothC](../models/rothc.md): monthly soil carbon turnover. |

The [Models](../models/index.md) section covers the theory and the inputs and outputs of each.
These pages are the signatures.

## Drivers

Forcing variables derived from what datasets distribute, each module a catena module of its own.

| Module | Produces |
| --- | --- |
| [`viresco.drivers.humidity`](modules/viresco.drivers/humidity.md) | `vpd`, from dewpoint, specific humidity or relative humidity. |
| [`viresco.drivers.radiation`](modules/viresco.drivers/radiation.md) | `ppfd`, from shortwave radiation or SPLASH. |
| [`viresco.drivers.pressure`](modules/viresco.drivers/pressure.md) | `pressure`, from elevation. |
| [`viresco.drivers.interpolate`](modules/viresco.drivers/interpolate.md) | Daily `fapar` and `co2`, from coarser series. |

The [Drivers](../drivers/index.md) page shows how a config uses them.

## Couplings

| Module | Produces |
| --- | --- |
| [`viresco.couplings`](modules/viresco.couplings.md) | One model's outputs as another's inputs, each selected by `<target>_from = "<source>"`. |

## Testing

`viresco.testing` writes configs and synthetic inputs for the test suite and for developing a model before it has real data.
Its config generator adds the resamples and couplings between models that `catena init` leaves out.

| Name | Does |
| --- | --- |
| [`get_builtin_models`](modules/viresco.testing/config_gen.md#viresco.testing.config_gen.get_builtin_models) | The model and driver names `generate_config` accepts. |
| [`get_model_config`](modules/viresco.testing/config_gen.md#viresco.testing.config_gen.get_model_config) | The settings one model accepts, with their defaults and descriptions. |
| [`generate_config`](modules/viresco.testing/config_gen.md#viresco.testing.config_gen.generate_config) | A runnable config for a chosen set of models, inputs and outputs wired up. |
| [`generate_synthetic_data`](modules/viresco.testing/data_gen/generate.md#viresco.testing.data_gen.generate.generate_synthetic_data) | Input files for every `[inputs.*]` section a config names. |

### Modules

| Module | Contents |
| --- | --- |
| [`viresco.testing.config_gen`](modules/viresco.testing/config_gen.md) | Reading a model's signatures to work out what it needs, and writing the TOML that supplies it. |
| [`viresco.testing.aggregations`](modules/viresco.testing/aggregations.md) | Variables coarsened by something other than a mean, and the aggregation they get instead. |
| [`viresco.testing.data_gen.generate`](modules/viresco.testing/data_gen/generate.md) | Config in, input files out. |
| [`viresco.testing.data_gen.spec`](modules/viresco.testing/data_gen/spec.md) | What a variable's generator is handed: the grid, the calendar, and the values already computed. |
| [`viresco.testing.data_gen.daily`](modules/viresco.testing/data_gen/daily.md) | The daily variables with a hand-written generator. |
| [`viresco.testing.data_gen.static`](modules/viresco.testing/data_gen/static.md) | The same for time-invariant variables. |
| [`viresco.testing.data_gen.fallback`](modules/viresco.testing/data_gen/fallback.md) | What a variable gets when no table entry names it: a kind inferred from the name, and noise to match. |

## Shared

| Module | Contents |
| --- | --- |
| [`viresco.temporal`](modules/viresco.temporal.md) | The temporal resolutions a pipeline speaks in, and the pandas offsets behind them. |

[catena-api]: https://nerc-ceh.github.io/catena/reference/python-api.html
