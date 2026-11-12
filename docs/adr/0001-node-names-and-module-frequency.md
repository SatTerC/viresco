# 1. Node names and module frequency

Status: accepted, November 2026; amended the same month to return off-frequency nodes to their models (see the end).

## Context

catena wires a pipeline by name, in one flat namespace: a node's parameter names are the names of the nodes it consumes.
A pipeline can hold one variable at several resolutions, so viresco suffixed every time-varying node with its resolution, daily included (`temperature_daily`).
A pipeline at daily resolution throughout carried the suffix for nothing.
Modules from other packages with bare daily names, such as xharvest's, did not match.

## Decision

- Daily is the finest resolution viresco models, and daily nodes have bare names: `temperature`.
  Weekly and monthly nodes keep `_weekly` and `_monthly`, and static nodes stay bare.
- A bare name therefore means daily or static, so anything that needs a node's frequency reads its declared `Freq`, never its name.
- Each model module runs at one frequency: SPLASH daily, the P-model and SGAM weekly, RothC monthly.
  A node at another frequency stays in its model's module only if that model alone uses it, and only by name in the allow-list in `tests/test_module_frequency.py`, which enforces the rule.
  Today those are the P-model's `mean_growth_temperature` and SGAM's `disturbances`.
- A node that belongs to no single model, such as a pedotransfer function or a derived variable, goes in the `viresco.nodes` subpackage, beside `viresco.models`, in a module named for what it does.
  We expect this collection of stand-alone nodes to grow alongside the process models.

## Consequences

- A config sets `suffix = ""` on its daily `[inputs.*]` and `[outputs.*]` sections, and `from = ""` on each `[[resample]]` from daily.
- A node's settings live in its model's section, off-frequency nodes included: `growing_season_limit` is a key of `[sgam]`.
- A pipeline enables the section of every stand-alone module it uses.
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

## Amendment: off-frequency nodes return to their models

As first accepted, the decision moved every node that did not run at its model's frequency out of the model, into a module `viresco.models.shared` with its own `[shared]` section.
Both nodes moved there were used by one model only: `mean_growth_temperature` is a pyrealm acclimation input for two P-model methods, and `disturbances` wraps `sgam.Disturbances`.
So every P-model or SGAM pipeline that used them needed an extra section for no reuse, a model's settings were split across two sections, and `shared` had to import P-model internals to know when its node was needed.
A module named for "doesn't fit" would also have collected unrelated nodes as it grew.
The rule now allows a model's own off-frequency nodes by name, and a module outside the models is kept for nodes that really belong to none.
