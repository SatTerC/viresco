# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "marimo",
#     "matplotlib==3.10.9",
#     "ukceh-viresco==0.8.0",
#     "ukceh-catena",
# ]
#
# [tool.uv.sources]
# ukceh-viresco = { path = "../.." }
# # TODO: pin to a catena release tag once catena and viresco stop changing in step.
# ukceh-catena = { git = "https://github.com/NERC-CEH/catena", branch = "main" }
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", app_title="Full pipeline")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Wiring four models into one pipeline

    This recipe builds a pipeline out of all four of Viresco's models at once: SPLASH for the water balance, the P-model for photosynthesis, SGAM for plant carbon allocation, and RothC for soil carbon.

    The models are the easy part.
    None of the four knows the others exist, and none of them imports another.
    Each declares its inputs by parameter name and its outputs by return value, and catena matches those names when it builds the DAG.
    So the pipeline is not really four models; it is four models plus the joins between them, and the joins are where the work is.

    This notebook takes its time over those joins.
    Two models connect only when the name *and* the units line up, and between these four they mostly do not, so the recipe carries a module of bridges, each converting one model's output into the next one's input.
    We will draw each join as its own small graph before running anything.

    The recipe is a directory, [`recipes/full_pipeline`](https://github.com/SatTerC/viresco/tree/main/recipes/full_pipeline):

    | File | Contents |
    |---|---|
    | `config.toml` | The pipeline: the four models, the bridges, the inputs and the outputs |
    | `nodes.py` | The bridges between the models |
    | `make_data.py` | Writes stand-in inputs to `data/` |
    | `demo.py` | This notebook |

    To run it, download the directory, or clone the repository, and open the notebook with [marimo](https://marimo.io):

    ```sh
    git clone https://github.com/SatTerC/viresco.git
    marimo edit --sandbox viresco/recipes/full_pipeline/demo.py
    ```
    """)
    return


@app.cell
def _():
    from pathlib import Path

    import catena
    import marimo as mo
    import matplotlib.pyplot as plt
    from catena.graph import _node_maps as node_maps
    from catena.graph import relabel_with_units
    from catena.importing import import_user_module

    recipe_dir = Path(__file__).parent
    config_path = recipe_dir / "config.toml"
    nodes_path = recipe_dir / "nodes.py"
    (recipe_dir / "results").mkdir(exist_ok=True)
    return (
        catena,
        config_path,
        import_user_module,
        mo,
        node_maps,
        nodes_path,
        plt,
        recipe_dir,
        relabel_with_units,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What each model needs and produces

    SPLASH is a bucket water balance.
    Give it precipitation, temperature and sunshine fraction, and it returns soil moisture, runoff, and both potential and actual evapotranspiration.

    The P-model computes photosynthesis from light, CO2, vapour pressure deficit and the water available to the plant.
    It reports gross primary productivity, light use efficiency and intrinsic water use efficiency.

    SGAM takes that carbon and allocates it to leaf, stem and root pools, and puts what the plant sheds into a litter pool.

    RothC decomposes soil carbon.
    Its input is the carbon arriving from litter; its outputs are the soil organic carbon pools and heterotrophic respiration.

    Read down that list and the chain is obvious: water limits photosynthesis, photosynthesis feeds allocation, allocation feeds the soil.
    Read it again looking at the *names* and the units, and the chain stops being obvious, because SPLASH does not produce anything called what the P-model asks for.
    """)
    return


@app.cell(hide_code=True)
def _(config_path, mo):
    mo.md(f"""
    ## The configuration

    Four `[<model>]` sections activate the modules.
    Everything else in the file exists to connect them:

    - `[bridges]` imports `nodes.py`, below, which defines the bridges between the models, and sets their two settings.
    - `[[resample]]` changes the frequency of a variable, which is how a daily model feeds a weekly one.
    - `[inputs.*]` and `[outputs.*]` say what is read from and written to disk.

    ```toml
    {config_path.read_text()}
    ```
    """)
    return


@app.cell(hide_code=True)
def _(mo, nodes_path):
    mo.md(f"""
    ## The bridges

    Each bridge is an ordinary function, named for the node it produces, whose parameters name the nodes it consumes.
    Its annotations declare the units and frequency of what goes in and comes out, and catena checks them across the whole DAG before anything runs.
    Nothing converts units between nodes, so a bridge that changes a unit says so: `xra.units.convert` where the change is a conversion, and `@xra.stamp_output_units(overwrite=True)` to label the output with its declared unit where the arithmetic leaves the input's label on it.
    The docstrings are worth reading; each records why its conversion is what it is.

    ```python
    {nodes_path.read_text()}
    ```
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Building the driver

    Parsing the config gives a `ParsedConfig`, and `build_driver` turns that into a Hamilton driver.
    Building is also when catena checks the whole graph's contracts, comparing the units, dimensions and temporal frequency each node declares against what its dependencies actually supply.
    A mis-wired pipeline therefore fails here, in under a second, rather than part-way through a long run.
    That check is what makes the bridges below safe to get wrong: a missing unit conversion is a build error, not a quietly incorrect carbon budget.

    The pipeline needs some twenty inputs, so `make_data.py` writes stand-ins with viresco's synthetic-data generator, which knows a plausible range, unit and seasonal shape for each.
    Point the `[inputs.*]` paths at real files to run on your own data instead.
    """)
    return


@app.cell
def _(import_user_module, recipe_dir):
    make_data = import_user_module(str(recipe_dir / "make_data.py"))
    input_paths = [p.relative_to(recipe_dir) for p in make_data.write_inputs()]
    input_paths
    return (input_paths,)


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
    return (dr,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Looking at one join at a time

    The whole DAG runs to over a hundred nodes, which is far too many to look at.
    `visualize_path_between` draws only the sub-graph connecting two nodes, and each model contributes a node under its own name, so `show_path("pmodel", "sgam")` draws exactly the wiring between those two models.

    Three settings do the tidying:

    - `strict_path_visualization=True` keeps the nodes on the path and drops their unrelated parents.
    - Hamilton draws every driver-config value as a floating `shape=note` box. They are unconnected to anything, so we filter them out of the rendered source.
    - The style we pass is *merged* into Hamilton's own defaults rather than replacing them. Hamilton already does this for nested attribute dicts such as `graph_attr`, and `show_path` does the same for its per-call arguments, so changing the orientation of one graph does not silently discard the shared style.
    """)
    return


@app.cell
def _(dr, node_maps, relabel_with_units):
    #: Shared appearance for every sub-graph drawn below.
    GRAPH_STYLE = {
        "graph_attr": {"rankdir": "LR", "ranksep": "0.5", "bgcolor": "transparent"},
        "node_attr": {"fontsize": "11"},
    }

    def show_path(upstream, downstream, **graph_attr):
        """Draw the sub-DAG connecting two nodes, using the shared style.

        Keyword arguments update ``GRAPH_STYLE["graph_attr"]`` rather than
        replacing it, and Hamilton in turn merges the result into its own
        defaults, so each level adds to the one below it.
        """
        style = {key: dict(value) for key, value in GRAPH_STYLE.items()}
        style["graph_attr"].update(graph_attr)

        graph = dr.visualize_path_between(
            upstream,
            downstream,
            output_file_path=None,
            strict_path_visualization=True,
            show_legend=False,
            graphviz_kwargs=style,
        )
        unit_map, _ = node_maps(dr)
        relabel_with_units(graph, unit_map)
        # Driver-config values are drawn as unconnected notes; drop them.
        graph.body = [line for line in graph.body if "shape=note" not in line]
        return graph

    return (show_path,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### SPLASH to the P-model: water

    Two quantities cross, and neither crosses unchanged.

    SPLASH tracks soil moisture as a depth of water held in a bucket, in mm.
    The P-model wants volumetric water content, in m3 m-3.
    `volumetric_water_content` divides by the bucket's capacity to get relative saturation, then multiplies by 0.45, a representative porosity for mineral soil.
    Both models run daily, so the frequency does not change here.

    The aridity index is a different shape of problem.
    pyrealm's is climatological, potential evapotranspiration over precipitation with both terms accumulated across the whole record, so it is one number per pixel rather than a time series.
    SPLASH computes PET on its way to actual evapotranspiration and exposes it, so the bridge is a sum and a divide.
    """)
    return


@app.cell
def _(show_path):
    show_path("splash", "pmodel")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### The P-model to SGAM: carbon, and the unit conversions

    This is the join worth studying.
    Three quantities cross and two of them are in the wrong units, because `viresco.models.pmodel` is an honest wrapper: it reports what pyrealm computes, in pyrealm's units, rather than quietly converting on the way out.

    The frequency changes too: the P-model runs daily and SGAM weekly, so a `[[resample]]` makes weekly means of the P-model's outputs, and the bridges below act on those.
    Each bridge multiplies by a constant, so converting before or after averaging gives the same numbers.

    **Gross primary productivity.**
    pyrealm reports a flux in ug C m-2 s-1.
    SGAM wants a daily rate in g C m-2 d-1.
    That is 86400 s d-1 multiplied by 1e-6 g ug-1, a factor of 0.0864, which `xra.units.convert` works out from the two units.

    **Light use efficiency.**
    pyrealm defines LUE against PPFD, which is a *photon* flux, so the denominator is moles of photons.
    SGAM wants carbon per MJ of absorbed PAR.
    The conversion is 4.57 mol MJ-1, the standard photon content of PAR over the 400-700 nm band.
    That is a property of the light rather than of the units, so it is a setting, `par_photons_per_mj`, rather than a conversion.

    **Intrinsic water use efficiency** needs no bridge at all.
    pyrealm reports umol mol-1 and SGAM consumes umol mol-1, so only its weekly mean, `iwue_weekly`, sits between `pmodel` and `sgam` in the graph below.

    Look at the node names in the graph: the P-model produces `gpp_flux` and `lue_photon`, resampled to `gpp_flux_weekly` and `lue_photon_weekly`, while SGAM consumes `gpp_weekly` and `lue_weekly`.
    The unconverted quantities are deliberately named so that they cannot satisfy SGAM's inputs by accident.
    Wiring them together directly would take an edit, and the contract check would reject the units even then.
    """)
    return


@app.cell
def _(show_path):
    show_path("pmodel", "sgam")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### SGAM to RothC: from a stock to a flux

    One quantity crosses, and converting it is more than arithmetic.

    SGAM's `litter_pool` accumulates and never decreases, because decomposition is RothC's job rather than SGAM's.
    So the carbon entering the soil during a month is the pool's *increment*, not its level: difference the weekly pool, then sum those differences within each month.
    Taking the increment also picks up litter from disturbance events, which the individual turnover outputs leave out.

    Only then is there a unit conversion, from SGAM's g m-2 to RothC's t ha-1.
    The bridge does it with `xra.units.convert` rather than writing the factor of 100 by hand, so the declared units carry the conversion.
    """)
    return


@app.cell
def _(show_path):
    show_path("sgam", "rothc")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### SPLASH to RothC, and the whole chain at once

    The path from the first model to the last passes through both of the others, so this graph is the pipeline end to end.
    Drawn left to right like the others it comes out 2020 pixels wide and unreadable in a page column, so this one is drawn top to bottom instead.
    The per-call `rankdir` overrides the shared style's without discarding the rest of it.

    Two more bridges appear here, and both are about aggregating a daily rate into a monthly total.
    Summing a rate in mm d-1 over a month integrates it, because the daily timestep is one day, but the sum keeps the rate's `mm d-1` label.
    Each bridge declares `mm` and stamps it over the old label.
    That label is stated rather than checked, so the docstring of `_monthly_total` is what records why it is right.

    The choice of *which* water flux to send RothC matters more than the arithmetic.
    It is potential evapotranspiration, not actual.
    RothC's water balance is rainfall minus evaporative demand, and actual evapotranspiration has already been suppressed by exactly the dryness RothC is trying to compute, so feeding it in would double-count the limitation and hold the modelled soil too wet.
    """)
    return


@app.cell
def _(show_path):
    show_path("splash", "rothc", rankdir="TB")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Running it end to end

    `run` takes the config and does the rest: loads the inputs, builds the DAG, computes every variable the `[outputs.*]` sections name, and writes the three NetCDF files.

    It hands back a `RunReport`.
    `report.outputs` is one Dataset per output section, keyed by section name, and that is what the plots below read — so the files on disk are incidental here.
    `report.written` records where each one went.
    """)
    return


@app.cell
def _(catena, config_path, input_paths, recipe_dir):
    assert input_paths  # run after the data is written
    report = catena.run(config_path)
    outputs = report.outputs

    {
        written.label: str(written.path.relative_to(recipe_dir))
        for written in report.written
    }
    return (outputs,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Diagnostics

    One panel per model, averaged over the sixteen pixels, in the order the carbon travels.
    Each panel runs at its model's own frequency: SPLASH daily, the P-model and SGAM weekly, RothC monthly.

    What to look for is whether the chain behaves: soil moisture should cycle seasonally, productivity should track it, the plant pools should accumulate, and the soil pools should respond to litter arriving from above.
    """)
    return


@app.cell
def _(outputs, plt):
    _daily = outputs["daily"].mean(("y", "x"))
    _weekly = outputs["weekly"].mean(("y", "x"))
    _monthly = outputs["monthly"].mean(("y", "x"))

    _fig, _axes = plt.subplots(4, 1, figsize=(10, 12))

    _daily["soil_moisture"].plot(ax=_axes[0], color="tab:blue")
    _axes[0].set_title("SPLASH: soil moisture")

    _weekly["gpp"].plot(ax=_axes[1], color="tab:green")
    _axes[1].set_title("P-model: gross primary productivity")

    for _pool in ["leaf_pool", "stem_pool", "root_pool", "litter_pool"]:
        _weekly[_pool].plot(ax=_axes[2], label=_pool)
    _axes[2].set_title("SGAM: plant carbon pools")
    _axes[2].legend(ncols=4, fontsize="small")

    _monthly["soil_organic_carbon"].plot(ax=_axes[3], color="tab:brown")
    _axes[3].set_title("RothC: soil organic carbon (bars: heterotrophic respiration)")

    _twin = _axes[3].twinx()
    _twin.bar(
        _monthly["time"],
        _monthly["heterotrophic_respiration"],
        width=20,
        color="tab:orange",
        alpha=0.35,
    )
    _twin.set_ylabel("heterotrophic respiration [t ha-1]")

    for _ax in _axes:
        _ax.set_xlabel("")

    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Where the joins live, and why

    Every conversion in this recipe is a function in its own `nodes.py` rather than a line of Python inside a model wrapper.
    A wrapper that quietly converted pyrealm's GPP on the way out would leave the next person with no way to see the assumption, let alone change it without editing Viresco.
    Here the conversion sits in the pipeline, under the name of the node it produces, with a docstring that says why and annotations that catena checks.
    """)
    return


if __name__ == "__main__":
    app.run()
