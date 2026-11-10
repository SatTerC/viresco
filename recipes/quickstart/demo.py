# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "ukceh-viresco==0.8.0",
#   "ukceh-catena",
#   "marimo",
#   "matplotlib==3.10.9",
#   "xarray",
# ]
#
# [tool.uv.sources]
# ukceh-viresco = { path = "../.." }
# # TODO: pin to a catena release tag once catena and viresco stop changing in step.
# ukceh-catena = { git = "https://github.com/NERC-CEH/catena", branch = "main" }
# ///

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Quickstart")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Quickstart

    This guide builds a one-model pipeline from an empty directory and runs it on synthetic data:
    SPLASH, which computes soil moisture, evapotranspiration and runoff from daily climate.
    No data of your own is needed.

    The first half uses Viresco's command-line interface, a handful of commands that go from nothing to a file of results.
    The second half opens the result in Python, plots it, and changes the pipeline.

    The guide is a [marimo](https://marimo.io) notebook, [`recipes/quickstart/demo.py`](https://github.com/SatTerC/viresco/tree/main/recipes/quickstart/demo.py).
    You can read it here, or run it yourself:

    ```sh
    git clone https://github.com/SatTerC/viresco.git
    marimo edit --sandbox viresco/recipes/quickstart/demo.py
    ```

    `--sandbox`, which needs [uv](https://docs.astral.sh/uv/), installs everything the notebook needs, Viresco included.
    Otherwise, follow the [installation guide](installation.md) first.
    """)
    return


@app.cell
def _():
    import os
    import shlex
    import shutil
    import subprocess
    import sys
    import tomllib
    from pathlib import Path

    import catena
    import marimo as mo
    import matplotlib.pyplot as plt
    import xarray as xr

    return (
        Path,
        catena,
        mo,
        os,
        plt,
        shlex,
        shutil,
        subprocess,
        sys,
        tomllib,
        xr,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Part 1: In a terminal

    Each step below is one command, run from the directory the pipeline lives in.
    The notebook runs them for you, in `my_pipeline/` beside it, and shows what each one printed; in a terminal, type the line after the `$`.
    The directory is emptied first, as `viresco setup` will not overwrite a config that already exists.
    """)
    return


@app.cell(hide_code=True)
def _(Path, mo, os, shlex, shutil, subprocess, sys):
    workdir = Path(__file__).parent / "my_pipeline"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir()

    def sh(command: str) -> mo.Html:
        """Run ``command`` in ``workdir`` and show it with its output, as a terminal would.

        Executables are looked up beside this Python first, so that ``viresco``
        resolves in a ``--sandbox`` environment.
        """
        args = shlex.split(command)
        local = Path(sys.executable).parent / args[0]
        if local.exists():
            args[0] = str(local)
        result = subprocess.run(
            args,
            cwd=workdir,
            capture_output=True,
            text=True,
            env=os.environ | {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "88"},
        )
        output = (result.stdout + result.stderr).strip().replace(f"{workdir}/", "")
        if result.returncode:
            raise RuntimeError(f"`{command}` failed:\n{output}")
        return mo.md(f"```console\n$ {command}\n{output}\n```")

    def show_toml(path: Path, lead: str = "") -> mo.Html:
        """Show a TOML file as a highlighted block, after an optional sentence.

        One `mo.md` rather than a stack, so the docs export keeps it as markdown.
        """
        return mo.md(f"{lead}\n\n```toml\n{path.read_text()}\n```")

    return sh, show_toml, workdir


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Step 1: Generate a config

    A pipeline is described by a configuration file.
    `viresco setup` writes one for the models you choose.
    Run without options it asks which models you want; here `--models splash` chooses SPLASH, and `--defaults` accepts the default paths.

    /// admonition | `setup` is experimental
        type: warning

    The command and the configs it generates may change.
    See the [CLI reference](../reference/cli.md#viresco-setup) for its current limitations.
    ///
    """)
    return


@app.cell(hide_code=True)
def _(sh):
    setup = sh("viresco setup --models splash --defaults")
    setup
    return (setup,)


@app.cell(hide_code=True)
def _(setup, show_toml, workdir):
    assert setup
    config_path = workdir / "config.toml"

    show_toml(config_path, "This is the `config.toml` it wrote:")
    return (config_path,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Every section switches on one part of the pipeline:

    - `[splash]` is the model, with its settings. Viresco registers its models with [catena](https://github.com/NERC-CEH/catena), the framework it is built on, so the section name alone is enough to find it.
    - `[inputs.daily]` and `[inputs.static]` say which files to read, and which variables to take from each.
    - `[outputs.daily]` says which results to write, and where.

    Each input variable becomes a node of the pipeline named `{var}{suffix}`, where the suffix defaults to the section label:
    `temperature` under `[inputs.daily]` becomes `temperature_daily`, which is what SPLASH's input is called.
    Static variables are used under their bare names, so that section sets an empty `suffix`.
    Paths are relative to the config file.
    catena's [configuration reference](https://github.com/NERC-CEH/catena/blob/main/docs/reference/configuration.md) describes every section.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Step 2: Edit the config

    `setup` asks for every result SPLASH can produce.
    We only want soil moisture, so delete the other variables from `vars` under `[outputs.daily]`, leaving `"soil_moisture"`.
    In a terminal, open `config.toml` in any text editor and delete those lines; the notebook makes the same edit for you.
    The file is now:
    """)
    return


@app.cell(hide_code=True)
def _(catena, config_path, show_toml, tomllib):
    _config = tomllib.loads(config_path.read_text())
    _config["outputs"]["daily"]["vars"] = ["soil_moisture"]
    config_path.write_text(catena.config.Config(_config).dumps())
    trimmed = True
    show_toml(config_path)
    return (trimmed,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Step 3: Generate synthetic data

    The config says which variables the pipeline needs, so `viresco data-gen` can make up plausible values for each, with the right units, and write them to the input paths.
    `--grid 1 1` asks for a single pixel, and `--seed` makes the values reproducible.

    /// admonition | SPLASH needs a full calendar year
        type: note

    SPLASH estimates its initial soil moisture by iterating over the first calendar year.
    The default start date falls in a leap year, so `--duration 1y`, which is 365 days, fails with "Cannot equilibrate - less than one year of data".
    Use `2y` or more.
    ///
    """)
    return


@app.cell(hide_code=True)
def _(sh, trimmed):
    assert trimmed
    data_gen = sh("viresco data-gen config.toml --grid 1 1 --duration 2y --seed 42")
    data_gen
    return (data_gen,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Step 4: Check the pipeline

    A dry run checks everything a real run depends on without running the model:
    that the config parses, the inputs load, every node finds its inputs, the units agree, and the outputs can be written.
    It is cheap, so run it whenever you change the config.

    /// tip | From Python
    `catena.dry_run("config.toml")` does the same, and returns a report of each stage.
    ///
    """)
    return


@app.cell(hide_code=True)
def _(data_gen, sh):
    assert data_gen
    dry_run = sh("viresco run config.toml --dry-run")
    dry_run
    return (dry_run,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Step 5: Draw the pipeline

    Viresco represents a pipeline as a graph: each node is an input or a computation, and an arrow runs from each node to those that use it.
    `viresco graph` draws it, and needs [graphviz](https://graphviz.org/download/) installed.
    `--png` writes `pipeline.png`, beside the graphviz source in `pipeline.dot`.

    /// tip | From Python
    `catena.build_graph("config.toml")` returns the same drawing, which a notebook displays as it is.
    ///
    """)
    return


@app.cell(hide_code=True)
def _(dry_run, sh):
    assert dry_run
    graph = sh("viresco graph --png config.toml")
    graph
    return (graph,)


@app.cell(hide_code=True)
def _(graph, mo, workdir):
    assert graph
    mo.image(workdir / "pipeline.png")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Read from left to right: the dashed box lists the inputs, the note lists SPLASH's settings, and the blue boxes are functions, SPLASH itself and the one that sets up its starting soil moisture.
    On the right is everything SPLASH computes.
    The drawing shows the whole pipeline, so every SPLASH result appears; the one the config asks for, `soil_moisture_daily`, is outlined.
    Each node shows its unit, which is what the dry run checked.

    ### Step 6: Run the pipeline

    `viresco run` reads the inputs, runs the model and writes soil moisture to `outputs/daily.nc`.
    The config that produced the file, and a hash of it, are stored in its attributes, so a result can be traced back to the config that made it.

    /// tip | From Python
    `catena.run("config.toml")` does the same, and also returns the results in memory.
    ///
    """)
    return


@app.cell(hide_code=True)
def _(dry_run, sh):
    assert dry_run
    run = sh("viresco run config.toml")
    run
    return (run,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Part 2: In Python

    The pipeline has run, and its results are in `outputs/daily.nc`.
    The rest of this guide is Python, starting from the files Part 1 left behind.

    ### Look at the results

    The output is an ordinary NetCDF file, so [xarray](https://xarray.dev) reads it as it is.
    `load_dataset` reads it into memory and closes the file, which the pipeline will write again below.
    """)
    return


@app.cell
def _(run, workdir, xr):
    assert run
    results = xr.load_dataset(workdir / "outputs" / "daily.nc")
    results
    return (results,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The soil fills to SPLASH's capacity each winter, and dries through the summer as evaporation outpaces rain.
    """)
    return


@app.cell
def _(plt, results):
    _fig, _ax = plt.subplots(figsize=(10, 3))
    results["soil_moisture"].squeeze().plot(ax=_ax, color="k", lw=1)
    _ax.set(title="", ylabel="Soil moisture (mm)")
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Change the pipeline

    The config is the pipeline, so changing what the pipeline does means changing the config.
    Parsed, a TOML file is an ordinary Python dictionary:
    """)
    return


@app.cell
def _(config_path, tomllib):
    config = tomllib.loads(config_path.read_text())
    config["outputs"]
    return (config,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Suppose you want weekly soil moisture as well, for instance to feed the P-model, which Viresco runs at a weekly step.
    catena's `[[resample]]` section aggregates a variable to a coarser step, so two additions give one:
    a `[[resample]]` that turns `soil_moisture_daily` into a weekly mean, `soil_moisture_weekly`,
    and an `[outputs.weekly]` section that writes it.
    Below they are added to the dictionary, which is written back to `config.toml`, as Step 2 did;
    in a text editor you would add the same lines by hand.
    """)
    return


@app.cell
def _(catena, config, config_path):
    config["resample"] = [
        {
            "vars": ["soil_moisture"],
            "from": "daily",
            "to": "weekly",
            "freq": "7D",
            "aggfunc": "mean",
        }
    ]
    config["outputs"]["weekly"] = {
        "path": "outputs/weekly.nc",
        "vars": ["soil_moisture"],
    }
    config_path.write_text(catena.config.Config(config).dumps())
    resampled = True
    return (resampled,)


@app.cell(hide_code=True)
def _(config_path, resampled, show_toml):
    assert resampled
    show_toml(config_path, "The config is now:")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Running the changed config writes both outputs.
    `catena.run` also returns them, one Dataset per output section, so there is no need to open the files.

    /// tip | From a terminal
    The change is saved in `config.toml`, so `viresco run config.toml --dry-run` checks it, and `viresco run config.toml` runs it, just the same.
    ///
    """)
    return


@app.cell
def _(catena, config_path, resampled):
    assert resampled
    report = catena.run(config_path)
    report.outputs["weekly"]
    return (report,)


@app.cell
def _(plt, report):
    _daily = report.outputs["daily"]["soil_moisture"].squeeze()
    _weekly = report.outputs["weekly"]["soil_moisture"].squeeze()
    _fig, _ax = plt.subplots(figsize=(10, 3))
    _ax.plot(_daily["time"], _daily, color="0.6", lw=1, label="daily")
    _ax.step(
        _weekly["time"], _weekly, where="post", color="k", lw=1.5, label="weekly mean"
    )
    _ax.set_ylabel("Soil moisture (mm)")
    _ax.legend()
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Next steps

    - To run on your own data, point each `path` under `[inputs.*]` at your files. Every variable needs a `units` attribute, which catena checks against the unit each model declares; the [model pages](../models/index.md) list them.
    - [My first pipeline](../recipes/my_first_pipeline.md) runs SPLASH on real data from a COSMOS-UK site, preparing the data with functions of your own.
    - Read about the [built-in models](../models/index.md) and how to combine them.
    - catena's [contracts](https://github.com/NERC-CEH/catena/blob/main/docs/concepts/contracts.md) page says what the checks can and cannot catch, and its [scale-up guide](https://github.com/NERC-CEH/catena/blob/main/docs/guides/run/scale-up.md) covers caching, blocking and parallel runs.
    """)
    return


if __name__ == "__main__":
    app.run()
