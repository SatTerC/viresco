# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "ukceh-viresco==0.8.0",
#   "ukceh-catena",
#   "marimo",
#   "matplotlib==3.10.9",
#   "xarray",
#   "xarray-annotated",
# ]
#
# [tool.uv.sources]
# ukceh-viresco = { path = "../.." }
# # TODO: pin to a catena release tag once catena and viresco stop changing in step.
# ukceh-catena = { git = "https://github.com/NERC-CEH/catena", branch = "main" }
# ///

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="My first pipeline")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Getting started with Viresco

    This notebook walks through running a Viresco pipeline step by step.
    It is aimed at users who are new to Viresco, and assumes only basic familiarity with Python.
    The pipeline runs the SPLASH water-balance model on two years of real weather from a [COSMOS-UK](https://cosmos.ceh.ac.uk/) site, and ends by comparing its soil moisture with what the site measured.

    The recipe is a directory, [`recipes/my_first_pipeline`](https://github.com/SatTerC/viresco/tree/main/recipes/my_first_pipeline):

    | File | Contents |
    |---|---|
    | `config.toml` | The pipeline |
    | `nodes.py` | Functions that prepare the COSMOS-UK data for SPLASH |
    | `data/cosmos.nc` | The COSMOS-UK data, downloaded with [xharvest](https://nerc-ceh.github.io/xharvest/) |
    | `demo.py` | This notebook |

    To run it, download the directory, or clone the repository, and open the notebook with [marimo](https://marimo.io):

    ```sh
    git clone https://github.com/SatTerC/viresco.git
    marimo edit --sandbox viresco/recipes/my_first_pipeline/demo.py
    ```

    `--sandbox`, which needs [uv](https://docs.astral.sh/uv/), installs everything the notebook needs, Viresco included, from the list at the top of `demo.py`.
    Drop it to use a Python environment that already has Viresco installed.

    Each step below is also a single command in a terminal, run from the recipe directory; the boxes say which.
    """)
    return


@app.cell
def _():
    import tomllib
    from pathlib import Path

    import catena
    import marimo as mo
    import matplotlib.pyplot as plt
    import xarray as xr

    recipe_dir = Path(__file__).parent
    config_path = recipe_dir / "config.toml"
    (recipe_dir / "results").mkdir(exist_ok=True)
    return catena, config_path, mo, plt, recipe_dir, tomllib, xr


@app.cell(hide_code=True)
def _(config_path, mo):
    mo.md(rf"""
    ## Step 1: The configuration

    A Viresco pipeline is described by a configuration file written in
    [TOML](https://toml.io/en/), a simple, human-readable format.
    The config schema is [catena](https://github.com/NERC-CEH/catena)'s; Viresco supplies the models.
    This is the recipe's `config.toml`:

    ```toml
    {config_path.read_text()}
    ```

    Every section activates a pipeline component:

    - `[inputs.cosmos]` and `[inputs.site]` load variables from the data file, each becoming a node of the pipeline.
      The list form names a node after the variable plus a suffix, which `suffix = ""` removes, so `ta` is the node `ta`.
      The mapping form names the node explicitly, so the file's `lat` coordinate is the node `latitude`.
    - `[cosmos_nodes]` loads the functions in `nodes.py`, and sets their `bucket_capacity`.
    - `[splash]` loads the SPLASH model, which Viresco registers with catena, so the section name alone is enough to find it.
      `sunshine_fraction_method = "shortwave"` tells it to work out the sunshine fraction it needs from measured radiation, as Step 3 explains.
    - `[outputs.daily]` saves the named variables to disk when the pipeline finishes.
      It sets `suffix = ""` because Viresco's daily nodes have [bare names](../models/index.md#node-names).

    Paths are relative to the config file.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### The same config as a dictionary

    TOML is only a serialisation format.
    Parsed, it is an ordinary Python dictionary, and everything downstream works from that, so the dictionary below is what catena actually sees.
    """)
    return


@app.cell
def _(config_path, tomllib):
    tomllib.loads(config_path.read_text())
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    `catena.config.Config` takes that dictionary directly, so you can build a config in Python if you want to:
    one per parameter value for a sweep, or a pipeline driven by another program that already holds the settings as data.

    It is worth knowing what you trade away.
    A TOML file is one artefact you can version, diff, review and pass to `viresco run`;
    a dictionary assembled over fifty lines of Python is none of those.
    Write the file by default, and reach for the dictionary when you are generating configs rather than authoring them.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 2: The input data

    [COSMOS-UK](https://cosmos.ceh.ac.uk/) is a network of soil moisture monitoring sites across the UK, each with its own weather station.
    `data/cosmos.nc` holds two years of daily data from Chimney Meadows (`CHIMN`), in Oxfordshire.
    It was downloaded with [xharvest](https://nerc-ceh.github.io/xharvest/), which fetches data from environmental data providers and writes it in a form catena reads as it is.
    The repository carries the file, so the notebook downloads nothing.

    /// tip | From a terminal
    Install xharvest's command-line tool once, with uv:

    ```sh
    uv tool install "xharvest[cosmos] @ git+https://github.com/NERC-CEH/xharvest"
    ```

    These two commands made `data/cosmos.nc`.
    The first downloads the raw data into `data/raw/`, and the second combines it into one netCDF file:

    ```sh
    xharvest cosmos fetch CHIMN --start 2021-01-01 --end 2022-12-31 \
      --parameter precip --parameter swin --parameter ta --parameter cosmos_vwc \
      --out data/raw
    xharvest cosmos standardise data/raw/CHIMN_1D_20210101_20221231.json --out data/cosmos.nc
    ```

    `fetch` names each file after the site and period, as `<site>_1D_<start>_<end>.json`.
    To try another site or period, change `CHIMN` and the dates in both commands.
    `xharvest cosmos sites` lists every site and its period of record.
    ///
    """)
    return


@app.cell
def _(recipe_dir, xr):
    cosmos = xr.open_dataset(recipe_dir / "data" / "cosmos.nc")
    cosmos
    return (cosmos,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Every variable carries a `units` attribute, and catena checks it against the unit each model input declares before the model sees the data.
    A missing label is an error, and so is a different unit, even one that could be converted:
    `swin` is in megajoules where SPLASH declares joules, so passing it straight in fails rather than being converted for you.
    """)
    return


@app.cell(hide_code=True)
def _(mo, recipe_dir):
    mo.md(rf"""
    ## Step 3: Preparing the data

    COSMOS-UK measures most of what SPLASH needs, but not quite in the form SPLASH takes it.
    `nodes.py` bridges the gap, with one ordinary Python function per SPLASH input:

    ```python
    {(recipe_dir / "nodes.py").read_text()}
    ```

    Each function is a node of the pipeline.
    Its name is the node it produces, and its parameters name the nodes it consumes, so `temperature(ta)` turns the input `ta` into the `temperature` SPLASH asks for.
    The `Unit` annotations are what catena checks: `shortwave_radiation` declares that it takes megajoules and returns joules, and converts in between.
    The gap filling is there because SPLASH carries soil moisture over from one day to the next, so it refuses any missing day in its inputs.

    `bucket_capacity`, after the `*`, is a setting rather than a node: its value comes from the `[cosmos_nodes]` section of the config.
    COSMOS-UK does not measure how much water the soil can hold, so here it is a fixed guess.
    The [soil moisture recipe](soil_moisture.md) calibrates it against the measurements instead.

    One input has no function here.
    SPLASH works out its radiation from a sunshine fraction, the share of daylight hours that are sunny, which COSMOS-UK does not measure.
    With `sunshine_fraction_method = "shortwave"`, Viresco recovers it from the measured shortwave radiation instead; the [SPLASH page](../models/splash.md) explains how.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 4: Build the pipeline

    Viresco represents a pipeline as a Directed Acyclic Graph (DAG): a network of nodes
    where each node is a computation, and edges show which computations depend on which others.
    Building the pipeline means constructing this graph from the config, and drawing it shows how the pieces fit together:
    the COSMOS-UK inputs, the functions in `nodes.py`, and SPLASH.
    Each node shows its unit, and the outputs the config asks for are highlighted.

    /// tip | From a terminal
    ```sh
    viresco graph --png config.toml
    ```

    writes the same drawing to `pipeline.png`, beside the graphviz source in `pipeline.dot`.
    It needs [graphviz](https://graphviz.org/download/) installed.
    ///
    """)
    return


@app.cell
def _(catena, config_path):
    catena.build_graph(config_path)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 5: Check the pipeline

    A dry run checks everything a real run depends on without running any model:
    that the config parses, the inputs load, every node finds its inputs, the units agree, and the outputs can be written.
    It is cheap, so run it whenever you change the config.

    /// tip | From a terminal
    ```sh
    viresco run --dry-run config.toml
    ```
    ///
    """)
    return


@app.cell
def _(catena, config_path, mo):
    dry = catena.dry_run(config_path)

    mo.md(
        "| Stage | Status | Detail |\n|---|---|---|\n"
        + "\n".join(
            f"| `{stage.name}` | {stage.status} | {stage.detail} |"
            for stage in dry.stages
        )
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 6: Run the pipeline

    `catena.run` does the whole thing in one call: it loads the inputs, builds the DAG, computes the variables `[outputs.daily]` names, and writes them to the path that section gives.

    What comes back is a `RunReport`.
    `report.outputs` holds one Dataset per output section, keyed by section name, so the results are in memory to explore and plot as well as on disk.
    `report.written` says where each file went and how large it is.

    /// tip | From a terminal
    ```sh
    viresco run config.toml
    ```

    writes the same `results/daily.nc`.
    ///
    """)
    return


@app.cell
def _(catena, config_path):
    report = catena.run(config_path)

    report.outputs["daily"]
    return (report,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 7: Compare with the measurements

    COSMOS-UK also measures soil moisture, so we can set SPLASH's against it.
    The two are not in the same units:
    SPLASH's soil moisture is the water in a bucket, in millimetres, while the probe measures the volumetric water content of the top few tens of centimetres, in percent.
    Plotted on separate axes, what to compare is the shape: when the soil wets up and dries out.
    Fitting `bucket_capacity` so the shapes agree is what the [soil moisture recipe](soil_moisture.md) does next.
    """)
    return


@app.cell
def _(cosmos, plt, report):
    soil_moisture = report.outputs["daily"]["soil_moisture"].isel(site=0)
    measured = cosmos["cosmos_vwc"].isel(site=0)

    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.plot(soil_moisture["time"], soil_moisture, color="tab:blue", lw=1)
    ax.set_ylabel("SPLASH soil moisture (mm)", color="tab:blue")
    twin = ax.twinx()
    twin.plot(measured["time"], measured, color="k", lw=1)
    twin.set_ylabel("COSMOS-UK water content (%)")
    fig.tight_layout()
    fig
    return


if __name__ == "__main__":
    app.run()
