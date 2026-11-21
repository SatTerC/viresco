---
title: Contributing a model
icon: lucide/hammer
---

# Contributing a model

This page is for adding a model, or a node that builds a model's inputs, to viresco.
Most of viresco's conventions are checked by its test suite, which reads every registered module and says what is missing or wrong, so this page spends its time on the decisions the tests cannot make for you.

The page follows [RothC](../models/rothc.md) throughout, as the smallest complete model: read `src/viresco/models/rothc.py` alongside it.

## Before you start

Open a [model proposal][proposal] before writing code, so that the questions below are settled while they are cheap to change.
The form asks each of them, along with the inputs, outputs and settings.

### Is it in scope?

Viresco covers processes in the terrestrial carbon, water and energy cycles at intermediate complexity: water balance, photosynthesis, vegetation and soil carbon pools, and the conversions that build their inputs from what datasets distribute.
Daily is the finest timestep; sub-daily models belong in another package.

### Does it fit a driven pipeline?

A viresco pipeline is a DAG in which each node runs once, over whole time series.
That allows a model to carry state through time, provided the state stays inside its node ([ADR 0002][adr-0002]):

- **State may live inside a node.** RothC integrates its soil pools from the first month to the last inside the `rothc` node.
- **State does not cross a node boundary.** No node may consume anything computed from its own output, directly or through other nodes.
- **Feedbacks between nodes are closed with observations.** Where a land-surface model would feed modelled LAI back into photosynthesis, a viresco pipeline uses observed LAI.
- **Forcing-only calculations are separate nodes.** A calculation that depends only on the forcings becomes its own node, so it can be swapped and reused; one that needs the model's state stays inside the model.

If the model cannot be run without exchanging state with another model every timestep, it does not fit viresco as it stands; say so in the issue.

### Model or node?

A **model module** runs at one frequency: SPLASH and the P-model daily, SGAM weekly, RothC monthly ([ADR 0001][adr-0001]).
A node at another frequency stays in the model's module only if that model alone uses it; SGAM's daily `disturbances` is the one example.

A node no single model owns, such as a pedotransfer function or a derived driver, goes in `viresco.nodes`, in a module named for what it does (`humidity`, `radiation`).

Node names carry the frequency as a suffix: bare for daily and static, `_weekly`, `_monthly`.
See [Node names](../models/index.md#node-names).

### Where does the science live?

Where a maintained Python implementation exists, viresco wraps it and depends on it: [pyrealm](https://github.com/ImperialCollegeLondon/pyrealm) for SPLASH and the P-model, [RothC_Py](https://github.com/SatTerC/RothC_Py) for RothC, `sgam` for SGAM.
The model's own code, its tests and its documentation of the science stay upstream; viresco holds the wrapper that makes it a set of DAG nodes.

Where no such package exists, a small model can be written here in numpy, and moved to its own package if it outgrows viresco.
Check the upstream licence before you start: viresco is MIT-licensed.

## Anatomy of a model module

A model module has three layers, plus any helper nodes it needs.

### 1. The kernel

A private function that runs the model for one cell, or one block of cells, on plain numpy arrays.
`_rothc_1px` takes `(time,)` series and per-cell scalars, calls `rothc_py`, and returns one `(time,)` array per output.
It knows nothing about xarray or the DAG.

### 2. The seam

A private function that maps the kernel over every cell with `xarray.apply_ufunc`.
`_rothc` takes the time dimension from the data with `catena.io.sole_time_dim`, declares it as the core dimension of the time series, and lets `apply_ufunc` broadcast every other dimension, whatever it is called:

```python
time = sole_time_dim(temperature_monthly, "temperature_monthly")
outputs = xr.apply_ufunc(
    _rothc_1px,
    temperature_monthly,
    ...,
    clay_content,
    input_core_dims=[[time]] * 7 + [[]] * 3,
    output_core_dims=[[time]] * 6,
    vectorize=True,
    dask="parallelized",
    output_dtypes=[float] * 6,
)
```

`apply_ufunc` drops the time coordinate and moves time last, so the seam reattaches the coordinate and puts time first.

Never write a dimension name (`"time"`, `"y"`, `"x"`, `"site"`) into the source: the models run on a grid, on a list of sites, or on a single point, and a test scans for them.
A kernel that needs a flat axis of cells, as SPLASH does to drop masked cells, reshapes in numpy inside the kernel.

### 3. The public node

The function the DAG sees, and the one the documentation renders:

```python
class RothCOut(TypedDict):
    """Outputs of the `rothc` node, at monthly resolution."""

    soil_organic_carbon_monthly: Annotated[DataArray, Unit("t ha-1"), MONTHLY]
    """Total soil organic carbon (tonnes of carbon per hectare)."""
    ...


@extract_fields()
@check_annotations
@stamp_output_units
def rothc(
    temperature_monthly: Annotated[DataArray, Unit("degC"), MONTHLY],
    clay_content: Annotated[DataArray, Unit("percent")],
    ...,
    *,
    n_years_spinup: int = 1,
    dpm_rate: float = 10.0,
) -> RothCOut:
    """
    Rothamsted Carbon model.

    Parameters
    ----------
    temperature_monthly
        Monthly mean air temperature (degrees Celsius).

    Other Parameters
    ----------------
    n_years_spinup
        Number of years of climate data used for model spin-up.
    """
```

- **Parameter names are node names.** catena connects `temperature_monthly` to whatever produces or loads a node of that name.
- **Every data input and output declares its units** with `Unit`, `Unit("1")` if dimensionless, and every time series its frequency with `DAILY`, `WEEKLY` or `MONTHLY` from `viresco.temporal`.
  `check_annotations` checks them against the data, and catena checks them across every edge of the DAG before anything runs.
- **Units are checked, never converted.** An input in kelvin where `degC` is declared raises.
  Convert where data enters the pipeline, and do not loosen a declaration to accept a second unit.
- **Settings are keyword-only, after `*`, with their defaults in the signature.**
  `viresco setup` writes them into the model's config section, and every section's keys share one namespace, so name them specifically (`dpm_rate`, not `rate`).
- **Several outputs are a `TypedDict`**, split into one node per field by `@extract_fields()`, with a docstring on each field.
- **Docstrings are numpydoc**, with data inputs under `Parameters`, settings under `Other Parameters`, and bare names with no `: type`.
  The model page renders the same docstring as its tables of inputs and settings.

### Helper nodes

A model often needs inputs no dataset supplies in its terms.
RothC's `plant_cover_monthly`, `dpm_rpm_ratio_monthly` and `farmyard_manure_input_monthly` build them from static data.
A helper that builds a time series from static data takes a time-bearing input, here `temperature_monthly`, purely for its calendar.
Settings on a helper stay on the helper: RothC's per-PFT DPM/RPM ratios are keyword-only arguments of `dpm_rpm_ratio_monthly`.

### A model too large for one module

A larger model is a subpackage, `src/viresco/models/<name>/`, laid out however suits it.
Its `__init__.py` imports the public nodes and their output `TypedDict`s from the submodules, lists them in `__all__`, and holds nothing else public:

```python
"""The <name> model."""

from ._canopy import canopy_conductance
from ._model import NameOut, name

__all__ = ["NameOut", "canopy_conductance", "name"]
```

catena, `viresco setup` and the tests all find a module's nodes as Hamilton does: the public functions in its namespace that are defined in it or in one of its submodules.
So everything in this page applies to the package as a whole: one frequency, one config section, one entry point naming the package.
A stateless piece that another model could use belongs in `viresco.nodes` instead.

## Register it

1. Add the module to the `catena.modules` entry points in `pyproject.toml`, and run `uv sync`:

    ```toml
    [project.entry-points."catena.modules"]
    rothc = "viresco.models.rothc"
    ```

    This is the one list of models: `viresco setup`, the docs graphs and the tests all read it.

2. Import it and add it to `__all__` in `src/viresco/models/__init__.py`.
3. Run `just test`.
   `tests/test_registry.py` names each page the model still lacks; see [Document it](#document-it).

A node at another frequency than its model needs an entry in `OFF_FREQUENCY` in `tests/test_module_frequency.py`.

## Test it

### What is checked for you

Once the module is registered, these run with nothing added:

| Test | Checks |
| --- | --- |
| `test_model_conformance.py` | Units on every data input and output, `check_annotations` on every node that declares any, settings with defaults under `Other Parameters`, bare docstring names, docstrings on output fields |
| `test_model_conformance.py` | The model alone, on the config `viresco setup` writes and the data `viresco data-gen` fills, with every contract enforced, on a grid, on sites and with renamed dimensions |
| `test_module_frequency.py` | One frequency per model module |
| `test_dims.py` | No dimension name in the source |
| `test_registry.py` | Docs and reference pages, nav entries, `__all__` |

A test failure names the node and the convention.
A variable that is categorical or a mask has no unit to declare; add it to `UNITLESS` in `test_model_conformance.py`, with the reason.

### Synthetic data

`viresco data-gen` writes plausible data for every input a config names, taking each variable's units from the node that declares it.
A variable with no entry in its tables gets noise inferred from its name, which is enough for most inputs.
Add a `Var` row to `src/viresco/scaffold/data_gen/daily.py` or `static.py` only where the structure matters: the model responds to seasonality, or another variable derives from it.

### What you write

**The seam test.** Subclass `SeamContract` from `tests/seam.py`, which checks the seam against an independent reference, the output dimensions, that distinct cells give distinct outputs, chunked against eager inputs, and a cached against an uncached run:

```python
class TestRothCSeam(SeamContract):
    seam = staticmethod(_rothc)
    outputs = _ROTHC_OUTPUT_NAMES
    dates = MONTHLY_DATES
    differs = "soil_organic_carbon_monthly"
    module = "viresco.models.rothc"
    node_config: ClassVar = {"n_years_spinup": 1}
    cached_output = "soil_organic_carbon_monthly"

    @pytest.fixture(scope="class")
    def seam_inputs(self, rothc_inputs):
        return rothc_inputs

    @pytest.fixture(scope="class")
    def reference(self, rothc_inputs):
        return _reference_loop(rothc_inputs)

    @pytest.fixture
    def node_inputs(self): ...
```

`seam_inputs` holds a few cells on `(time, pixel)` whose inputs differ, since a seam that mixes up cells passes on identical ones.
`reference` computes each output without the seam, usually by looping the upstream package over the cells; see `tests/test_rothc_seam.py`.

**Tests of the science.** A model's own tests belong upstream, but the wrapper must still be shown to give the upstream model's answers in viresco's units.
Pin a few outputs against published values or the upstream package's own examples; `tests/test_pyrealm_units.py` does this for pyrealm, with its golden values regenerated by `just regen-pyrealm-golden` only after reviewing why they changed.
Test anything the wrapper adds: spin-up, masked cells, a method choice, a conversion.

## Document it { #document-it }

1. **A model page**, `docs/models/<name>.md`, following [SPLASH](../models/splash.md): overview, theory, then usage as quickstart, configuration, inputs, outputs and Python API, then references.
   The overview inlines the DAG from `docs/models/_graphs/<name>.svg`, which `just graph <name>` renders and `just docs` regenerates; copy the `model-graph` block from `docs/models/rothc.md`.
   The tables of settings, inputs and outputs are rendered from the signatures and docstrings with `:::` blocks; copy them from `docs/models/rothc.md`.
   Do not restate in prose anything a table already says.
   The theory section is where the science goes: the equations, the assumptions, and where viresco departs from the upstream model.

2. **A reference page**, `docs/reference/modules/viresco.models/<name>.md`, whose body is a `:::` block for `viresco.models.<name>`, like `rothc.md` beside it.
3. **Nav entries** for both, in `zensical.toml`, and a row in the table in `docs/models/index.md`.

Build the site with `just docs` to check it renders.

A recipe is welcome, though not required: a pipeline in `recipes/<name>/` with its config, data and a marimo notebook, on real data where possible.

## What a reviewer looks for

- The model fits a driven pipeline, and state stays inside its node.
- The science is upstream or in a module of its own, cited, with its assumptions in the theory section.
- Units are declared everywhere, and match the upstream model's conventions or document where they differ.
- The wrapper is shown to reproduce upstream values.
- `just` passes: lint, type checks and the full test suite.

[proposal]: https://github.com/SatTerC/viresco/issues/new?template=model-proposal.yml
[adr-0001]: https://github.com/SatTerC/viresco/blob/main/docs/adr/0001-node-names-and-module-frequency.md
[adr-0002]: https://github.com/SatTerC/viresco/blob/main/docs/adr/0002-driven-pipelines.md
