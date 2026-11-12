# 1. Node names and module frequency

Status: accepted, November 2026.

## Context

catena wires a pipeline by name, in one flat namespace: a node's parameter names are the names of the nodes it consumes.
A pipeline can hold one variable at several resolutions, so viresco suffixed every time-varying node with its resolution, daily included (`temperature_daily`).
A pipeline at daily resolution throughout carried the suffix for nothing.
Modules from other packages with bare daily names, such as xharvest's, did not match.

## Decision

- Daily is the finest resolution viresco models, and daily nodes have bare names: `temperature`.
  Weekly and monthly nodes keep `_weekly` and `_monthly`, and static nodes stay bare.
- A bare name therefore means daily or static, so anything that needs a node's frequency reads its declared `Freq`, never its name.
- Each model module runs at exactly one frequency: SPLASH daily, the P-model and SGAM weekly, RothC monthly.
  `tests/test_module_frequency.py` enforces this.
- A node that belongs to no single model lives in a module of its own, outside the model modules, as `mean_growth_temperature` and `disturbances` do in `viresco.models.shared`.
  We expect this collection of stand-alone nodes to grow, for example with pedotransfer functions and derived variables, alongside the process models.

## Consequences

- A config sets `suffix = ""` on its daily `[inputs.*]` and `[outputs.*]` sections, and `from = ""` on each `[[resample]]` from daily.
- A pipeline enables the section of every stand-alone module its models consume from, such as `[shared]` for SGAM's disturbance detection.
- A model's resolution is fixed by its parameter names, so the same model module cannot run at different resolutions in different pipelines.

## Rejected: rebinding a module's inputs from config

The alternative was for model code to use bare names everywhere, with a module's config section choosing a resolution (`input_suffix = "_weekly"`).
catena would then have copied the module's functions with rewritten signatures, binding each input `x` the module does not produce itself to `x_weekly`, with an `inputs` mapping for exceptions such as static inputs.
We tested a prototype against viresco and rejected it:

- To work out what a module produces, it needs Hamilton's node names, not function names.
  `@config.when` variants such as `kphio_inputs__sandoval` produce `kphio_inputs`, which the prototype rewrote to `kphio_inputs_weekly`.
  Fixing this means building each module's graph, with its config, before rewriting it.
- Rewritten functions keep their Hamilton decorators only because `functools.wraps` copies the function's `__dict__`, which is a Hamilton internal.
  Decorators that name their own dependencies (`@parameterize` with `source`, `@inject`, `@subdag`) break.
- A binding can go wrong without an error.
  An optional input defaulting to `None` would be renamed and then ignored.
  A coarse input that declares no `Freq` would escape the contract check.
- Connections between two weekly modules would each need an exception, unless the section renamed outputs as well as inputs.
  That would recreate the hard-coded suffixes the mechanism was meant to remove.

Its one real gain, running the same module at different resolutions, is something no viresco model needs: SPLASH needs consecutive days, RothC is monthly by design, and SGAM is written weekly.
If a model ever does need it, revisit this decision, and derive a module's produced nodes from the built Hamilton graph.
