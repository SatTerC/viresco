# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "ukceh-viresco==0.8.0",
#   "ukceh-catena",
#   "marimo",
#   "matplotlib==3.10.9",
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

    The recipe is a directory, [`recipes/my_first_pipeline`](https://github.com/SatTerC/viresco/tree/main/recipes/my_first_pipeline):

    | File | Contents |
    |---|---|
    | `config.toml` | The pipeline |
    | `make_data.py` | Writes stand-in inputs to `data/` |
    | `demo.py` | This notebook |

    To run it, download the directory, or clone the repository, and open the notebook with [marimo](https://marimo.io):

    ```sh
    git clone https://github.com/SatTerC/viresco.git
    marimo edit --sandbox viresco/recipes/my_first_pipeline/demo.py
    ```

    `--sandbox`, which needs [uv](https://docs.astral.sh/uv/), installs everything the notebook needs, Viresco included, from the list at the top of `demo.py`.
    Drop it to use a Python environment that already has Viresco installed.
    """)
    return


@app.cell
def _():
    import tomllib
    from pathlib import Path

    import catena
    import marimo as mo
    import matplotlib.pyplot as plt
    from catena.importing import import_user_module

    recipe_dir = Path(__file__).parent
    config_path = recipe_dir / "config.toml"
    (recipe_dir / "results").mkdir(exist_ok=True)
    return catena, config_path, import_user_module, mo, plt, recipe_dir, tomllib


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

    Every section activates a pipeline component.
    `[splash]` loads the SPLASH water-balance module, which Viresco registers with catena so the section name alone is enough to find it.
    `[inputs.daily]` loads daily climate data from the given path, and `[outputs.daily]` saves the named variables to disk when the pipeline finishes.
    Paths are relative to the config file.

    Node names are `{{var}}{{suffix}}`, with the suffix defaulting to the section label,
    so `temperature` under `[inputs.daily]` becomes the node `temperature_daily`,
    which is what SPLASH's parameter is called.
    Static variables are consumed under bare names, so that section sets `suffix = ""`.
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
def _(mo, recipe_dir):
    mo.md(rf"""
    ## Step 2: The input data

    Viresco reads input data from NetCDF or Zarr files, detecting the format from the file extension in the config.
    This recipe has no real data to hand, so `make_data.py` writes two years of plausible daily climate at one site.
    It is also a template for your own data: one file per `[inputs.*]` section, with a `units` attribute on every variable.

    ```python
    {(recipe_dir / "make_data.py").read_text()}
    ```

    ### A note on units

    Every model input in Viresco declares the units it expects, and catena checks the data against that declaration before the model sees it.
    The check reads the `units` attribute on each array, and NetCDF keeps it.

    A missing label is an error, and so is a different unit, even one that could be converted:
    `degF` where `degC` is declared fails rather than being converted for you.
    Convert your data before it enters the pipeline.
    The [model docs](../models/splash.md) list the unit each input is declared in.
    """)
    return


@app.cell
def _(import_user_module, recipe_dir):
    make_data = import_user_module(str(recipe_dir / "make_data.py"))
    input_paths = [path.relative_to(recipe_dir) for path in make_data.write_inputs()]
    input_paths
    return (input_paths,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 3: Build the pipeline

    Viresco represents a pipeline as a Directed Acyclic Graph (DAG): a network of nodes
    where each node is a computation, and edges show which computations depend on which others.

    Building the pipeline means constructing this graph from the modules and configuration you specified.
    Below we draw the part of the graph running from the daily precipitation input to the soil moisture output.
    """)
    return


@app.cell
def _(catena, config_path):
    config = catena.load_config(config_path)
    dr = catena.build_driver(
        modules=config.modules,
        config=config.driver_config,
        node_specs=config.node_specs,
        base=config.base,
        registered=config.registered_modules,
    )
    dr.visualize_path_between(
        "precipitation_daily",
        "soil_moisture_daily",
        show_legend=False,
        graphviz_kwargs={"graph_attr": {"ratio": "compress", "size": "10,15"}},
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 4: Run the pipeline

    `catena.run` does the whole thing in one call: it loads the inputs, builds the DAG, computes the variables `[outputs.daily]` names, and writes them to the path that section gives.
    From a terminal, `viresco run config.toml` does the same.

    What comes back is a `RunReport`.
    `report.outputs` holds one Dataset per output section, keyed by section name, so the results are in memory to explore and plot as well as on disk.
    `report.written` says where each file went and how large it is.

    Note that `run` takes the config, not the driver we built in step 3.
    That step was to see the graph; running the pipeline does not need it.
    """)
    return


@app.cell
def _(catena, config_path, input_paths):
    assert input_paths  # run after the data is written
    report = catena.run(config_path)

    report.outputs["daily"].info()
    return (report,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 5: Inspect the results

    Let us plot the simulated soil moisture over the two-year period.
    Soil moisture rises after precipitation events and falls during dry periods,
    so a clear seasonal signal should be visible.
    """)
    return


@app.cell
def _(plt, report):
    soil_moisture = report.outputs["daily"]["soil_moisture"].isel(site=0)

    fig, ax = plt.subplots(figsize=(10, 3))
    soil_moisture.plot(ax=ax)
    ax.set_ylabel("Soil moisture (mm)")
    fig.tight_layout()
    fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Using your own data

    1. Write each input section to a NetCDF file, following `make_data.py`: a `units` attribute on every variable, and a time dimension with dates on it.
       A gridded file, with `y` and `x` dimensions and a coordinate reference system, works too; catena then computes `latitude` itself, so it can come out of `[inputs.static]`.
    2. Change each `path` in `config.toml` to point at your file.
    3. Run the pipeline, either by re-running this notebook without the `make_data` cell, or from a terminal with `viresco run config.toml`.
    """)
    return


if __name__ == "__main__":
    app.run()
