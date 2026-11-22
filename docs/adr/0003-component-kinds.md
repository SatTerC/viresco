# 3. Component kinds: models, drivers and couplings

Status: accepted, November 2026.
Supersedes the ownership rule of [ADR 0001](0001-node-names-and-module-frequency.md) ("a node that belongs to no single model … goes in `viresco.nodes`"); its naming and one-frequency rules for model modules stand.

## Context

By November 2026 four criteria were in use to decide where a node goes, and they disagreed:

| Criterion | Where it was stated | What it said |
| --- | --- | --- |
| Ownership | ADR 0001 | A node no single model owns goes in `viresco.nodes` |
| State | Issue #72 | A stateless module belongs in `nodes` rather than `models` |
| Frequency | `tests/test_module_frequency.py` | A model module runs at one frequency |
| Purpose | `docs/nodes/index.md` ("Input nodes") | Nodes build the P-model's drivers from what datasets distribute |

ACM is stateless and lived in `models`; the proposed respiration (#72), pedotransfer (#67) and root-distribution (#68) modules are science of the same standing, stateless or static, and their issues put them in `nodes`.
By ACM's precedent they were models; by #72's reasoning, ACM was a node.

The split had consequences beyond naming:

- `viresco setup`, `just graph-all` and the tests that run each module alone read `viresco.models` only, so a module in `nodes` could not be chosen in setup or run alone.
- The frequency test rejected a module that declares no frequency, so a static model could not live in `models`.
- `shortwave_radiation` was declared in `J m-2 d-1` by SPLASH and in `W m-2` by ACM and `radiation`, so no pipeline could load it for both; nothing checked a name's unit across modules.
- Three proposed modules (#68–#70) each declared a `soil_layer_thicknesses` setting.
  `viresco setup` writes every setting's default into its module's section, and catena raises on a key set in two sections, so setup could not write a working config for them.
- Conversions between one model's outputs and another's inputs lived in three places: a table in `viresco.scaffold.bridges` that the config generator turned into `[[node]]` expressions, `recipes/config.toml`, and two recipes' `nodes.py`, which copied four functions verbatim.
  Some carried constants with no documentation outside a docstring: a soil porosity, the photon content of PAR, the Falloon et al. (1998) equation.
  Three open issues (#70, #72, #73) each relied on "a recipe bridge".

## Decision

### Nodes are placed by what they are

Who uses a node changes whenever a module is added, so a rule based on it moves files around; what a node is does not change.

| Kind | Test | Lives in |
| --- | --- | --- |
| **Model** | Its variants, or its alternatives, differ by scientific hypothesis or by the data they were fitted to | `viresco.models.<name>` |
| **Model-internal node** | Encodes one model's own definitions or parameters | That model's module, prefixed with the model's name where the name is otherwise generic |
| **Driver** | Derives a forcing variable from data, with variants that differ only in which data are available; consumes no model output | `viresco.drivers.<variable family>` |
| **Coupling** | Turns one model's output into another model's input | `viresco.couplings` |

The test between a model and a driver is one question: *do the variants disagree about the science, or only about the data available?*
The three routes to VPD (from dewpoint, specific humidity or relative humidity) compute one quantity from different data, so `humidity` is a driver.
Cosby, Saxton–Rawls and Wösten pedotransfer functions are competing fitted relationships, so `pedotransfer` is a model.

Statefulness, frequency and the number of consumers do not decide location.
A model may be stateful, stateless or static, and may be one node or several.
A model module still runs at one frequency, or is static (ADR 0001).

### Couplings are package code, chosen by their target

`viresco.couplings` is one registered module.
Each function is named `<target>__<source>` and is selected by a key named for its target, `<target>_from = "<source>"`, as drivers' variants are:

```toml
[couplings]
volumetric_water_content_from = "splash"
soil_carbon_input_monthly_from = "sgam"
```

A coupling has no default variant, so a key left unset adds no node, and the section is harmless when enabled.
A coupling that carries a physical constant takes it as a setting and says where it comes from.
`viresco setup` writes these keys where it used to write `[[node]]` expressions.

### Time behaviour is declared on each node

State belongs to a node, not to a module: one model may have stateless and stateful nodes.
There are three behaviours, because each has different consequences for a user:

| Behaviour | Meaning | Consequence |
| --- | --- | --- |
| `pointwise` | Each step is computed from that step's inputs | Results do not depend on when the run starts or how long it is |
| `record` | Reads a window or the whole record, but carries no state | Results depend on the period run |
| `stateful` | Integrates a state from an initial condition | Needs spin-up or an initial state; calibrate against data that do not drive it (ADR 0002) |

`viresco.temporal.time_behaviour` declares it; a node with no declaration is `pointwise`.
The conformance tests check the declarations: the outputs of a chain of `pointwise` nodes are the same when the run is cut to its first half, and a `stateful` node takes a spin-up setting (`<model>_spinup_years`) or initial-state input (`initial_<state>`), the names new models use.

### One name, one unit

A node name has one unit and one frequency across every registered module, and a test enforces it.
The same pass over the annotations generates the documentation's variable catalogue.

### Structure shared between models is a node

A quantity that several models must agree on, such as the thicknesses of the soil layers, is produced by one node and consumed as an input, rather than repeated as a setting in each module.

### Every model declares its domain

`DOMAIN` in each model module names the process it represents, from a fixed list in `viresco.registry`.
The documentation groups models by domain, so that alternatives sit side by side.
Two models that produce the same name are alternatives: catena will not load both.

## Consequences

- `viresco.nodes` is renamed `viresco.drivers`.
  `ppfd__splash`, which consumed a SPLASH output, is a coupling.
- Respiration, pedotransfer functions and root distributions are models, with model pages, and can be chosen in `viresco setup`.
- `viresco setup`, the config generator and the conformance tests read models, drivers and couplings alike.
- `scaffold/bridges.py` and the recipes' copied conversions are removed; recipes enable `[couplings]`.
- ACM's `days_from_midsummer` becomes `acm_days_from_midsummer`, and RothC's `n_years_spinup` becomes `rothc_spinup_years`.
- A static module passes the frequency test.
- The time-behaviour declaration is generic enough to belong in catena, where it would allow blocking along time; propose it there once it has settled here.
