---
title: Overview
icon: lucide/package
---

# Built-in models

`viresco` comes with the models below, which can be composed into a pipeline.
A model is a scheme whose alternatives disagree about the science; the [drivers](../drivers/index.md) derive forcing variables from data, and the [couplings](../couplings.md) turn one model's outputs into another's inputs.

Viresco registers every model with catena, so a config names one by its section alone.

```toml
[splash]
soil_moisture_init_max_iter = 10
```

Models that produce the same variable are alternatives: a pipeline loads one of them.

--8<-- "docs_tools/_generated/models.md"

## Time behaviour { #time-behaviour }

Each node declares how it behaves in time, and the tests check the declaration.
The table gives the behaviour of each model's own node, and names any of its other nodes that read other steps.

| Behaviour | Meaning | What it asks of you |
|-----------|---------|---------------------|
| Pointwise | Each step is computed from that step's inputs alone | Nothing: the result does not depend on when the run starts or how long it is |
| Record | Reads a window of steps, or the whole record, but carries no state | Expect the result to depend on the period run |
| Stateful | Integrates a state from an initial condition | Choose a spin-up or an initial state; calibrate against data that do not drive the model |

A stateful model's results depend on its spin-up and on the first years of forcing, so two runs over different periods disagree where they overlap until the state has forgotten its start.
Calibrating one against an observation that also drives the pipeline is not an independent test ([ADR 0002][adr-0002]).

## How the models connect { #connections }

Each box is a model or a driver, with its time behaviour; stateful ones are drawn in bold.
An edge is a variable one produces and the other consumes, directly or, where marked, through a coupling.

<div class="model-graph">
--8<-- "docs_tools/_generated/components.svg"
</div>

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
`recipes/config.toml` writes them that way.

Because daily and static names are both bare, a name alone does not say which a node is: its declared frequency does.



## Inputs on a grid { #inputs-on-a-grid }

The models take whatever dimensions their inputs have besides time: a grid `(y, x)`, a set of sites, or a single point.
catena passes each input on as its file holds it, and every cell is modelled independently.

`latitude` is an ordinary input, read from a file like any other.
viresco's synthetic data writes it as a variable.
A file that carries it as a coordinate binds it with the mapping form of `vars`:

| File | Binding |
|------|---------|
| A latitude-longitude grid | `vars = { latitude = "y" }` |
| A projected grid with a CF `lat` coordinate | `vars = { latitude = "lat" }` |
| A station file with a `lat` coordinate on `site` | `vars = { latitude = "lat" }` |

catena does not check that gridded inputs share a grid unless a config asks it to, and xarray's default inner join silently drops the cells that do not line up.
A config with gridded inputs in several sections should therefore add these checks:

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
[adr-0002]: https://github.com/SatTerC/viresco/blob/main/docs/adr/0002-driven-pipelines.md
