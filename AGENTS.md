# AGENTS.md

Viresco is in **alpha** with no users outside the core collaboration. Backwards
compatibility is *not* a constraint: prefer the cleanest design and make breaking
changes (config schema, public APIs, behaviour) freely rather than adding
compatibility shims.

## Architecture / what lives where

Viresco is a thin domain package on top of [**catena**](https://github.com/NERC-CEH/catena), which owns the framework:
config parsing, the DAG, contract validation, I/O, caching, blocking, subsetting,
parallel subset I/O, and the CLI (`init`, `run`, `graph`, `subset`).
viresco has no CLI of its own: users run catena's commands, which find
viresco's modules through the `catena.modules` entry points. `viresco.testing`
holds the config and synthetic-data generators, for the test suite and for
developers, not for users.
catena passes inputs to nodes with the dimensions their files have (its ADR
0003): it does not stack a grid, add `latitude`/`longitude`, or check that
gridded inputs share a grid unless a config's `[validation]` asks it to.
catena's **`main` branch is the source of truth** — read it (or the local
checkout, if present) rather than guessing at its API.

## Gotchas

- All common tasks run via `just` (see `justfile`) — no need to invoke `pytest`/`uv run` directly.
- Pre-commit hooks only run `uv-lock`, `pyright`, and `ruff` — not the full test suite.
- A recipe is a directory, `recipes/<name>/`, holding a `config.toml`, any node module it needs, its data (with the notebook giving the xharvest commands that fetched it) or a `make_data.py` that writes it, and the marimo notebook as `demo.py`, as catena's recipes do. A conversion between two models is a coupling in `viresco.couplings`, never a function in the recipe; put any other conversion (of a dataset's variables) in the node module as a real function rather than a `[[node]]` expression, and prefer real data to synthetic. `just export <name>` renders the notebook into `docs/recipes/`; only the recipes in `documented_recipes` in the `justfile`, which must match the Recipes nav in `zensical.toml`, are published, while `tests/test_recipes.py` dry-runs and runs every recipe's config. The exception is `recipes/quickstart/`, the quickstart guide: it has no committed config, because it runs `catena init` and the other catena commands itself in a scratch `my_pipeline/`, with synthetic data from `viresco.testing`, and `just export-quickstart` publishes it as `docs/guides/quickstart.md`; `tests/test_quickstart.py` runs it. Notebooks pin `ukceh-viresco==<version>` in inline `# dependencies` — update when bumping the package version, then re-export with `just export-all`.
- Plain config files under `recipes/` are **not** loaded by any code or tooling — they are user-facing references only, so nothing will catch a mistake in them. Check `recipes/config.toml` by filling its inputs with `viresco.testing.data_gen.generate_synthetic_data`, then `catena run --dry-run`.
- Documentation uses **zensical** (markdown, mkdocstrings-material-like), **not** Sphinx/rst.
  Two rendering traps: `pymdownx.snippets` acts on a `--8<--` line even inside a
  fenced code block (escape it as `;--8<--`, or describe it instead), and inline
  code starting with `::: ` renders without that prefix. List continuations and
  nested blocks need four spaces; three ends the list.
- Synthetic data is table-driven: a variable is one `Var` row (units, long name,
  one generator lambda) in `testing/data_gen/daily.py` or `static.py`. Adding
  a model's inputs means adding rows, not writing generator functions. A variable
  with no row still generates — `fallback.py` infers plausible noise from the
  name, labelled with the unit the consuming node declares — so only add a row
  where the *structure* matters: the model responds to seasonality, or another
  variable derives from it. A coarse section holds a per-period total where the
  declared unit is the daily unit times a day (`mm d-1` summed onto `mm`), else a
  mean. Each entry is a module-level constant with a docstring, so the docs pick
  it up with no extra step.
- Model documentation pages have four sections, in order: Overview (ending
  with the DAG and the generated guide links), Theory (the science, ending with
  the fitted ranges, for a fitted model), Details (the implementation: which
  equations from which source, and where it departs from them) and Reference.
  Reference is the snippet `just catalogue` generates from the signatures,
  contracts and docstrings, and holds no prose; do not restate in prose anything
  its tables say. Until NERC-CEH/catena#64, inputs that only a non-default
  `@config.when` variant needs are hand-written `:::` blocks after the snippet,
  as in `pmodel.md` and `splash.md`. Citations are inline links to a DOI or URL,
  with no references list. Write numpydoc parameters as a bare name with no
  `: type`: griffe renders the docstring type in place of the annotation, which
  empties the Annotations column of the API reference.
- Configurable settings are keyword-only arguments, after a bare `*`, on the
  node that consumes them, with their defaults in the signature. Document them
  under numpydoc `Other Parameters`, not `Parameters`: the generated Reference
  reads its settings table from `Other Parameters` and its inputs table from
  `Parameters`. Settings on a non-model node stay on that node: rothc's per-PFT
  DPM/RPM ratios are on `dpm_rpm_ratio_monthly` and the growing-season gate on
  `sgam.disturbances`. `get_model_config` in `config_gen.py` reads the
  keyword-only defaults off every public function in the module, so a new
  setting is picked up with no change there; the keys still land flat in the one
  `[<model>]` section. Do not group settings into a config node or TypedDict.
  Prefix a setting with the model's name where it would otherwise be generic
  (`acm_canopy_height`, but `dpm_rate`).
- A model with state, or one wrapping an upstream package, is one node; a model
  without state whose science is written here may be several, split where
  variants of the model differ (`models/acm.py`). How a node computes is the
  developer's call, subject to review: a numpy kernel mapped by an
  `apply_ufunc` seam (`models/rothc.py`) or xarray throughout
  (`models/acm.py`). Intermediate nodes carry the model's prefix, return time
  first, and in xarray use `stamp_output_units(overwrite=True)` and
  `xr.ufuncs`. A seam with no core dimension still needs one `[]` per output in
  `output_core_dims`.
- Model DAG graphs are generated, not committed: `just graph <model>` writes
  `docs/models/_graphs/<model>.svg`, and `just docs` depends on `graph-all` so a
  docs build always renders them fresh. `graph-all` loops over the registered
  models. Likewise `just catalogue` (`scripts/render_catalogue.py`) writes the
  models overview table, the variable catalogue, the couplings table, the
  graph of models and drivers, each model page's Reference section
  (`reference/<model>.md`) and its links to guides (`guides/<model>.md`) into
  `docs_tools/_generated/`, which the pages
  include as snippets; edit the script, not the pages, to change them.
- The `catena.modules` entry points in `pyproject.toml` are the one list of
  model, driver and coupling modules, read through `viresco.registry`; run `uv sync` after
  adding one. `tests/test_registry.py` checks the `__all__` lists, docs pages,
  nav and the lists of modules in `docs/index.md` and `python-api.md` against it, and `tests/test_model_conformance.py` checks every registered
  module's signatures and docstrings, and runs each model alone on synthetic data
  with contracts enforced.
- `docs/contributing/models.md` is the contributor-facing account of the
  conventions in this file; change it when they change.
- A model's required tests are the ones that run with nothing written: the
  declared contracts and the run alone on synthetic data, in
  `tests/test_model_conformance.py`. Plausibility of that run (#80) is not
  required yet. Highly recommended, and asked for in review: a seam test,
  subclassing `SeamContract` in `tests/seam.py`, which needs the seam, an
  independent reference (usually a per-cell loop over the upstream package) and
  inputs for a cached node run; and a test reproducing a paper's or another
  implementation's numbers. For a model of stateless nodes the seam is
  `driver_seam`, which runs the module through a catena driver, and where the
  science is written here the reference is a scalar transcription of the
  equations. A new model's tests go in `tests/test_<model>.py`. An input read
  only for its calendar goes in `TIME_ONLY` in
  `tests/test_model_conformance.py`.
- A model is a module, `models/<name>.py`, or a subpackage, `models/<name>/`, as
  the developer prefers, subject to review. A subpackage's `__init__.py` imports its nodes and their output
  `TypedDict`s from the submodules, lists them in `__all__`, and exports
  nothing else. A module's nodes are
  whatever `hamilton.graph_utils.find_functions` returns, which takes in a
  subpackage's submodules; `config_gen` and the tests use it, and must not
  filter on `func.__module__ == module.__name__`. `tests/toy_subpackage/` is the
  test-only example that fails a check which misses submodule nodes.
- A node is placed by what it is, not by who uses it
  (`docs/adr/0003-component-kinds.md`). A **model** (variants that differ by
  scientific hypothesis or fitted data; stateful, stateless or static) is
  `viresco.models.<name>`. A **model-internal node** (the model's own
  definitions or parameters) stays in its model's module, prefixed with the
  model's name where the name is otherwise generic; one at another frequency
  goes in `OFF_FREQUENCY` in `tests/test_module_frequency.py`. A **driver**
  (derives a forcing variable from data, variants differ only by the data
  available, consumes no model output) goes in `viresco.drivers`, one module
  per variable family. A **coupling** (one model's output to another's input)
  goes in `viresco.couplings`, named `<target>__<source>` and selected by
  `@config.when(<target>_from="<source>")` with no default. Never copy a
  conversion into a recipe's `nodes.py`.
- Every node that is not `pointwise` declares its time behaviour with
  `@time_behaviour("record")` or `@time_behaviour("stateful")` from
  `viresco.temporal`; `tests/test_time_behaviour.py` checks the declarations. A
  stateful node takes a `<model>_spinup_years` setting or an `initial_<state>`
  input.
- A node name has one unit and one frequency across every registered module
  (`tests/test_variables.py`). Structure several models must agree on (soil
  layer thicknesses) is a node they consume, not a setting each declares.
- Every model module sets `DOMAIN` to one of `viresco.registry.DOMAINS`.
- Module settings share one flat namespace: catena merges every section's keys
  into a single Hamilton config, and raises if two sections set the same key. A
  keyword-only default is not a setting until a config sets it, so two nodes may
  share a setting name, and then one value serves both, as
  `par_photons_per_mj` does for `radiation.ppfd__shortwave` and
  `couplings.lue__pmodel`. Set it in one section only; `config_gen` writes it in
  the first section that declares it, and raises if two defaults differ.
- xarray-annotated checks units, it never converts them: an input whose
  `units` attribute differs from the declared one raises, even where pint could
  convert (kelvin for degC, `%` for `1`). Convert at the point data
  enters, with `xarray_annotated.units.convert` or in the fetching notebook, and
  do not loosen a declaration to accept a second unit.
- Models work on whatever non-time dimensions their inputs have: `(y, x)`, a
  `site`, or none. Each takes the time dimension from `sole_time_dim` and lets
  `xarray.apply_ufunc` map over the rest; nothing stacks to one spatial
  dimension, and no dimension name is written into the source.
  `tests/test_dims.py` runs the example pipeline on a grid, on the same data
  stacked to `site`, and with every dimension renamed, and expects the same
  numbers. A kernel that needs a flat axis of cells (SPLASH, to drop masked
  cells) reshapes in numpy inside its block function.
- `latitude` is an ordinary input, read from a file: a variable, as `data_gen`
  writes it, or a coordinate bound with the mapping form of `vars` (`{ latitude
  = "y" }` on a latitude-longitude grid, `{ latitude = "lat" }` for a CF
  projected grid's 2-D coordinate or a station file). `config_gen` also writes
  `crs_equal` and `coords_equal` checks over the gridded input sections.
- Generic behaviour belongs upstream. If a change would be useful to a pipeline
  that is not about carbon, it probably belongs in catena, not here.

## Releasing

Every PR merges to `main`; a release is a tag on it, made by the maintainer only.
Nothing is published to PyPI: users install a tag from GitHub.

1. `uv version --bump rc` (giving e.g. `0.9.0rc1`), or `--bump stable` for a
   full release. Update the `ukceh-viresco==` pins in `recipes/*/demo.py` to match, run
   `just export-all`, and commit. `just tag` refuses if a pin is stale.
2. `just tag`, then `just release`.
3. After a full release, `uv version --bump minor --bump dev`, update the recipe
   pins again, and commit, so a git install of `main` does not report the
   released version.

The docs site deploys only on a stable release (or a manual `workflow_dispatch`),
so it documents the latest release.

## Config schema

The schema is catena's; there is no viresco-specific config code.


## Block size is not numerically free

`[blocking]` and `[subset]` partition one dimension of the inputs (`y` on a grid,
so a block is whole rows), and SPLASH's results
depend slightly on that partition: `estimate_initial_soil_moisture` iterates to a
convergence tolerance evaluated over the whole block, so a different block size
stops at a different iteration. The effect is ~1e-4 relative on `soil_moisture`
and `actual_evapotranspiration`.
Therefore, don't expect bit-identical output when comparing runs with different
`block_size`, different `[subset]` ranges, or blocked against unblocked. Do
expect it for the same partition.
