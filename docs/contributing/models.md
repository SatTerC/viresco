---
title: Contributing a model
icon: lucide/hammer
---

# Contributing a model

This page is for adding a model, a driver or a coupling to viresco.
Most of viresco's conventions are checked by its test suite, which reads every registered module and says what is missing or wrong, so this page spends its time on the decisions the tests cannot make for you.

The page follows [RothC](../models/rothc.md) throughout, as the smallest complete model: read `src/viresco/models/rothc.py` alongside it.

## Before you start

Open a [model proposal][proposal] before writing code, so that the questions below are settled while they are cheap to change.
The form asks each of them, along with the inputs, outputs and settings.
If an issue for the model already exists, answer the form's questions in a comment on it instead.

### Is it in scope?

Viresco covers processes in the terrestrial carbon, water and energy cycles at intermediate complexity: water balance, photosynthesis, vegetation and soil carbon pools, and the conversions that build their inputs from what datasets distribute.
Daily is the finest timestep; sub-daily models belong in another package.

### Does it fit a driven pipeline?

A viresco pipeline is a DAG in which each node runs once, over whole time series.
That allows a model to carry state through time, provided the state stays inside its node ([ADR 0002][adr-0002]):

- **State may live inside a node.** RothC integrates its soil pools from the first month to the last inside the `rothc` node.
- **State does not cross a node boundary.** No node may consume anything computed from its own output, directly or through other nodes.
- **Feedbacks between nodes are closed with observations.** Where a land-surface model would feed modelled LAI back into photosynthesis, a viresco pipeline uses observed LAI.
- **Forcing-only calculations are separate nodes.** A quantity the model computes from the forcings alone, such as ACM's days from midsummer, becomes its own node, so it can be swapped and reused; a calculation that needs the model's state stays inside the model.

If the model cannot be run without exchanging state with another model every timestep, it does not fit viresco as it stands; say so in the issue.

### One node or several?

A model that carries state through time is one node, because its state cannot cross a node boundary: RothC and SPLASH integrate inside their nodes.
So is a model that wraps an upstream package, stateless or not, because the package owns how its pieces connect: the P-model is one node around pyrealm.

A model without state whose science is written here is a few nodes instead ([ACM](../models/acm.md)).
Split it where variants of the model differ, or where an intermediate has a meaning of its own, so that a variant replaces one node and keeps the rest.
Do not split a calculation that is solved as a whole: ACM's internal CO2, diffusion and light limitation are one steady-state solution, and stay in one node.
[A model of stateless nodes](#a-model-of-stateless-nodes) says how to write one.

### Model, driver or coupling?

A node is placed by what it is, not by which modules use it ([ADR 0003][adr-0003]).
The question that decides most cases is: *do the variants disagree about the science, or only about the data available?*

| Kind | What it is | Where it goes |
| --- | --- | --- |
| **Model** | Variants or alternatives that differ by hypothesis or by the data they were fitted to; stateful, stateless or static | `viresco.models.<name>` |
| **Model-internal node** | One model's own definitions or parameters, such as RothC's DPM/RPM ratios by plant type | The model's module, prefixed with its name where the name is otherwise generic (`acm_days_from_midsummer`) |
| **Driver** | A forcing variable derived from data, whose variants differ only in the data they start from, such as VPD from dewpoint or from relative humidity | `viresco.drivers`, in a module named for the variable family (`humidity`, `radiation`) |
| **Coupling** | One model's output turned into another model's input | `viresco.couplings`, named `<target>__<source>` |

Pedotransfer functions are a model, though static and used by several others, because Cosby and Saxton–Rawls disagree about the science.
VPD from dewpoint is a driver, because every route gives the same quantity and the choice is set by the data you have.
A driver never consumes a model's output; a node that does is a coupling.

A model module runs at one frequency, or is static: SPLASH, the P-model and ACM daily, SGAM weekly, RothC monthly ([ADR 0001][adr-0001]).
A model-internal node at another frequency stays in the model's module; SGAM's daily `disturbances` is the one example, and it is listed in `OFF_FREQUENCY` in `tests/test_module_frequency.py`.

Node names carry the frequency as a suffix: bare for daily and static, `_weekly`, `_monthly`.
See [Node names](../models/index.md#node-names).
A name has one unit and one frequency across every module, and `tests/test_variables.py` fails on a second.

### Does it carry state?

Declare how each node behaves in time, since it decides what a user must do to run it:

| Behaviour | Meaning | Declaration |
| --- | --- | --- |
| `pointwise` | Each step from that step's inputs | none |
| `record` | Reads a window or the whole record, carries no state | `@time_behaviour("record")` |
| `stateful` | Integrates a state from an initial condition | `@time_behaviour("stateful")` |

`time_behaviour` is in `viresco.temporal`.
The tests check a `pointwise` node by running it on the first half of the record, and a `stateful` one for a spin-up setting named `<model>_spinup_years` or an initial-state input named `initial_<state>`.

### Shared structure

Something several models must agree on, such as the thicknesses of the soil layers, is a node they consume, not a setting each declares.
Two modules declaring the same setting share one value, so their defaults must agree.

### Where does the science live?

Where a maintained Python implementation exists, viresco wraps it and depends on it: [pyrealm](https://github.com/ImperialCollegeLondon/pyrealm) for SPLASH and the P-model, [RothC_Py](https://github.com/SatTerC/RothC_Py) for RothC, `sgam` for SGAM.
The model's own code, its tests and its documentation of the science stay upstream; viresco holds the wrapper that makes it a set of DAG nodes.

Where no such package exists, a small model can be written here, in numpy or in xarray, and moved to its own package if it outgrows viresco.
Check the upstream licence before you start: viresco is MIT-licensed.
Code without a licence cannot be ported; write the model from its published equations instead, as ACM is.

## Anatomy of a model module

How a node computes is your call, subject to review: a numpy kernel mapped over the cells by an `apply_ufunc` seam, as RothC does, or xarray throughout, as ACM does.
So is the layout: one module, or a [subpackage](#a-model-in-a-subpackage).
What follows is RothC's way, a kernel behind a seam, which suits a model that is one node around an upstream package.
A model of several stateless nodes in xarray has no kernel or seam; see [below](#a-model-of-stateless-nodes).

A model that is one node around a kernel has three layers, plus any helper nodes it needs.

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

A kernel with no state in time, such as one wrapping a stateless upstream function, declares no core dimension at all, so that `apply_ufunc` hands it whole blocks rather than looping over cells.
`output_core_dims` must then still list one `[]` per output; without it `apply_ufunc` expects one output, and fails with "Received 0 dimension(s)".

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
    rothc_spinup_years: int = 1,
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
    rothc_spinup_years
        Number of years of climate data used for model spin-up.
    """
```

- **Parameter names are node names.** catena connects `temperature_monthly` to whatever produces or loads a node of that name.
  An input another module already reads must be declared in the unit it already has, since a pipeline holding both passes one array to each; search `src/viresco` for the name.
- **Output names share that namespace.** An output with the name of an existing node must be the same quantity in the same unit; a different quantity gets a different name, as ACM's `gpp` (g m-2 d-1) and the P-model's `gpp_flux` (ug m-2 s-1) do.
- **Every data input and output declares its units** with `Unit`, `Unit("1")` if dimensionless, and every time series its frequency with `DAILY`, `WEEKLY` or `MONTHLY` from `viresco.temporal`.
  `check_annotations` checks them against the data, and catena checks them across every edge of the DAG before anything runs.
- **Units are checked, never converted.** An input in kelvin where `degC` is declared raises.
  Convert where data enters the pipeline, and do not loosen a declaration to accept a second unit.
- **Settings are keyword-only, after `*`, with their defaults in the signature.**
  `catena init` writes them into the model's config section, and every section's keys share one namespace, so name them specifically (`dpm_rate`, not `rate`).
  Prefix a name with the model's where it would otherwise be generic (`acm_canopy_height`); one already specific to the model, such as `dpm_rate`, needs no prefix.
- **A setting is one value for the whole domain.** A parameter that describes a site and can vary in space, such as foliar nitrogen, is better a static data input.
  If it is a setting, its docstring or the model page says which site its default comes from.
- **Several outputs are a `TypedDict`**, split into one node per field by `@extract_fields()`, with a docstring on each field.
- **Docstrings are numpydoc**, with data inputs under `Parameters`, settings under `Other Parameters`, and bare names with no `: type`.
  ruff wants the summary line in the imperative: "Run the Aggregated Canopy Model", not "Aggregated Canopy Model".
  The model page renders the same docstring as its tables of inputs and settings.

### Helper nodes

A model often needs inputs no dataset supplies in its terms.
RothC's `plant_cover_monthly`, `dpm_rpm_ratio_monthly` and `farmyard_manure_input_monthly` build them from static data.
A helper that builds a time series from static data takes a time-bearing input, here `temperature_monthly`, purely for its calendar.
Settings on a helper stay on the helper: RothC's per-PFT DPM/RPM ratios are keyword-only arguments of `dpm_rpm_ratio_monthly`.

### A model of stateless nodes

A model without state is a few public nodes in one module, each plain xarray arithmetic, with no kernel and no `apply_ufunc` seam: xarray broadcasts the inputs, whatever their dimensions, and the result works on dask arrays unchanged.
`src/viresco/models/acm.py` is the example: `acm_nitrogen_limited_capacity`, `acm_canopy_conductance` and `acm_seasonal_factor` feed `acm`, which returns the model's outputs.

- **The intermediate nodes are nodes like any other**, with units on every input and output and their settings on the node that uses them.
  Their names carry the model's prefix, because they are only meaningful inside it.
  An empirical intermediate still has a unit: ACM's canopy conductance is in `g m-2 d-1 ppm-1`, whatever turns a CO2 difference into a carbon flux.
- **Return time first**, by transposing on `sole_time_dim` of an input, since broadcasting orders dimensions by the inputs.
- **Use `stamp_output_units(overwrite=True)`**, since xarray arithmetic carries the inputs' `units` attribute onto the result.
- **Use `xr.ufuncs`** (`xr.ufuncs.exp`, not `np.exp`), which pyright knows return a `DataArray`.
- **The node returning the model's outputs is named for the model**, so the config section, the docs page and the main node agree.

### A model in a subpackage { #a-model-in-a-subpackage }

A model may be a subpackage, `src/viresco/models/<name>/`, rather than one module, laid out however suits it; that is your choice, usually made once a module grows too large to read.
Its `__init__.py` imports the public nodes and their output `TypedDict`s from the submodules, lists them in `__all__`, and holds nothing else public:

```python
"""The <name> model."""

from ._canopy import canopy_conductance
from ._model import NameOut, name

__all__ = ["NameOut", "canopy_conductance", "name"]
```

catena, `viresco.testing` and the tests all find a module's nodes as Hamilton does: the public functions in its namespace that are defined in it or in one of its submodules.
So everything in this page applies to the package as a whole: one frequency, one config section, one entry point naming the package.

## Register it

1. Add the module to the `catena.modules` entry points in `pyproject.toml`, and run `uv sync`:

    ```toml
    [project.entry-points."catena.modules"]
    rothc = "viresco.models.rothc"
    ```

    This is the one list of models: `catena init`, the docs graphs and the tests all read it.

2. Import it and add it to `__all__` in `src/viresco/models/__init__.py`, and set `DOMAIN` in the module to one of `viresco.registry.DOMAINS`.
3. Run `just test`.
   `tests/test_registry.py` names each page the model still lacks; see [Document it](#document-it).

A node at another frequency than its model needs an entry in `OFF_FREQUENCY` in `tests/test_module_frequency.py`.

## Test it

Imperfect is fine: where a test would take disproportionate work, cut the corner, say so in the pull request, and open an issue for it rather than block on it.

### Required: what is checked for you

The required tests are the ones that run once the module is registered, with nothing added:

| Test | Checks |
| --- | --- |
| `test_model_conformance.py` | Units on every data input and output, `check_annotations` on every node that declares any, settings with defaults under `Other Parameters`, bare docstring names, docstrings on output fields |
| `test_model_conformance.py` | The model alone, on the config and synthetic data `viresco.testing` writes, with every contract enforced, on a grid, on sites and with renamed dimensions |
| `test_module_frequency.py` | One frequency per model module |
| `test_dims.py` | No dimension name in the source |
| `test_registry.py` | Docs and reference pages, nav entries, `__all__` |

A test failure names the node and the convention.
A variable that is categorical or a mask has no unit to declare; add it to `UNITLESS` in `test_model_conformance.py`, with the reason.
An input read only for its calendar, as a helper node's is, declares no unit either; add the node and parameter to `TIME_ONLY` beside it.

### Synthetic data

`viresco.testing.data_gen` writes plausible data for every input a config names, taking each variable's units from the node that declares it.
A variable with no entry in its tables gets noise inferred from its name, which is enough for most inputs.
Add a `Var` row to `src/viresco/testing/data_gen/daily.py` or `static.py` only where the structure matters: the model responds to seasonality, another variable derives from it, or two variables must keep an order, as a daily maximum and minimum temperature must.
The conformance run checks that the model runs on this data, not that the data or the results are plausible, so look at both once.
A test of plausibility is not required for now ([#80](https://github.com/SatTerC/viresco/issues/80)).

### Highly recommended: what you write

These are not enforced, but a reviewer will ask for them, and a model without them needs a reason in the pull request.

**The seam test.** Subclass `SeamContract` from `tests/seam.py`, in `tests/test_<model>.py` beside the model's other tests.
It checks the seam against an independent reference, the output dimensions, that distinct cells give distinct outputs, chunked against eager inputs, and a cached against an uncached run:

```python
class TestRothCSeam(SeamContract):
    seam = staticmethod(_rothc)
    outputs = _ROTHC_OUTPUT_NAMES
    dates = MONTHLY_DATES
    differs = "soil_organic_carbon_monthly"
    module = "viresco.models.rothc"
    node_config: ClassVar = {"rothc_spinup_years": 1}
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
The seam is called with them as keyword arguments, so any settings it takes go in the same dict.
`reference` computes each output without the seam, usually by looping the upstream package over the cells; see `tests/test_rothc_seam.py`.

A model of stateless nodes has no seam function: its seam is the composition of its nodes, and `driver_seam(module, outputs)` from `tests/seam.py` runs them through a catena driver, taking inputs and settings as keyword arguments.

Where the science is written here, there is no package to loop over, so the reference is a scalar transcription of the published equations, evaluated one cell and day at a time with `math` (`tests/test_acm.py`).
That catches mistakes in broadcasting, units and wiring, but not a misreading of the paper the transcription shares, so a test against published values matters most here.

**Tests of the science.** A model's own tests belong upstream, but the wrapper should still be shown to give the upstream model's answers in viresco's units, and a model written here to reproduce a paper's or another implementation's numbers.
Pin a few outputs against published values or the upstream package's own examples; `tests/test_pyrealm_units.py` does this for pyrealm, with its golden values regenerated by `just regen-pyrealm-golden` only after reviewing why they changed.
Where a paper gives its model's outputs only in a figure, read them off, say in the test which figure and table they come from, and set a tolerance that covers the reading and the precision of the tabulated inputs; `tests/test_acm.py` does this for ACM's Toolik Lake sites.
Test anything the wrapper adds: spin-up, masked cells, a method choice, a conversion.

## Document it { #document-it }

1. **A model page**, `docs/models/<name>.md`, with four sections in this order:

    | Section | Holds |
    | --- | --- |
    | Overview | What the model is and does, where its code comes from, and the DAG, ending with the generated guide links |
    | Theory | The science: the equations and the assumptions, ending, for an empirical or fitted model, with its validity: the ranges of the drivers it was fitted over, and what is known of how it extrapolates |
    | Details | The implementation: which equations from which source, and where viresco departs from the upstream model or the paper |
    | Reference | Generated: the model's settings, inputs, outputs and intermediate nodes, with their units, frequencies and descriptions |

    Theory and Details explain; Reference is looked up, so it comes last and holds no prose.
    Write only Overview, Theory and Details: everything else on the page is generated from the code, so it cannot drift from it.
    Copy the skeleton from [ACM](../models/acm.md):

    ```markdown
    ---
    title: ACM
    icon: lucide/leaf
    ---

    # Aggregated Canopy Model (ACM)

    ## Overview

    ...

    <div class="model-graph">
    ;--8<-- "docs/models/_graphs/acm.svg"
    </div>

    ;--8<-- "docs_tools/_generated/guides/acm.md"

    ## Theory

    ## Details

    ## Reference

    ;--8<-- "docs_tools/_generated/reference/acm.md"
    ```

    The front matter gives a `title` and an `icon` from [Lucide](https://lucide.dev/icons/), as `lucide/<icon>`.
    `just docs` regenerates the DAG and the snippets; `just graph <name>` and `just catalogue` render them on their own.

    - **Reference** comes from the config `catena init -m <name>` writes, so its tables cover the variants the settings select by default.
      Until [NERC-CEH/catena#64](https://github.com/NERC-CEH/catena/issues/64), an input that only another variant needs gets a hand-written subsection after the snippet, with a `:::` block for the variant's node, as the [P-model](../models/pmodel.md) and [SPLASH](../models/splash.md) pages do.
    - **The guide links** list the documented recipes and the quickstart that run the model, read from their configs; they render nothing until one does.
    - **Citations are inline links** to a DOI or URL, in Theory or Details, such as `([Williams et al., 1997](https://doi.org/...))`.
      There is no references list.
    - **Do not restate in prose** anything the Reference tables say: a node's units and meaning belong in its docstring, where the table and the API reference both read them.

2. **A reference page**, `docs/reference/modules/viresco.models/<name>.md`, whose body is a `:::` block for `viresco.models.<name>`, like `rothc.md` beside it.
3. **Nav entries** for both, in `zensical.toml`: the model page under the Models section named for its `DOMAIN`, adding the section if it is the first model in that domain.
4. **The lists of models**: a row in the table of model modules in `docs/reference/python-api.md`, and a link in the Models entry of `docs/index.md`.
   The models overview table, the variable catalogue, the couplings table and the graph of how models connect are generated from the code by `just catalogue`, so they need nothing.

A driver needs a section on `docs/drivers/index.md` with the anchor `{ #<module> }`, and a coupling a `:::` block on `docs/couplings.md`.

`tests/test_registry.py` checks all of these.
Build the site with `uv run just docs`, or `just docs` in an activated environment, to check it renders.

A recipe is welcome, though not required: a pipeline in `recipes/<name>/` with its config, data and a marimo notebook, on real data where possible.

## What a reviewer looks for

- The model fits a driven pipeline, and state stays inside its node.
- The science is upstream or in a module of its own, cited inline, with its assumptions in Theory and its departures from the source in Details.
- Units are declared everywhere, and match the upstream model's conventions or document where they differ.
- Ideally, the wrapper is shown to reproduce upstream values, or a model written here to reproduce published ones; where it is not, the pull request says why.
- Corners cut are fine, provided each has an issue.
- A fitted model says over what ranges it was fitted.
- `just` passes: lint, type checks and the full test suite.

[proposal]: https://github.com/SatTerC/viresco/issues/new?template=model-proposal.yml
[adr-0001]: https://github.com/SatTerC/viresco/blob/main/docs/adr/0001-node-names-and-module-frequency.md
[adr-0002]: https://github.com/SatTerC/viresco/blob/main/docs/adr/0002-driven-pipelines.md
[adr-0003]: https://github.com/SatTerC/viresco/blob/main/docs/adr/0003-component-kinds.md
