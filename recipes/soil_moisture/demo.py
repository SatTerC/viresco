# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "marimo",
#     "matplotlib==3.10.9",
#     "numpy==2.4.4",
#     "ukceh-viresco==0.8.0",
#     "ukceh-catena",
#     "scipy==1.17.1",
#     "xarray==2026.4.0",
#     "xarray-annotated",
#     "xharvest[cosmos]",
# ]
#
# [tool.uv.sources]
# ukceh-viresco = { path = "../.." }
# # TODO: pin to a catena release tag once catena and viresco stop changing in step.
# ukceh-catena = { git = "https://github.com/NERC-CEH/catena", branch = "main" }
# xharvest = { git = "https://github.com/NERC-CEH/xharvest", branch = "main" }
# ///

import marimo

__generated_with = "0.23.5"
app = marimo.App(width="medium", app_title="Soil moisture calibration")


@app.cell
def _():
    from pathlib import Path

    import catena
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import xarray as xr
    from scipy.optimize import OptimizeResult, minimize

    recipe_dir = Path(__file__).parent
    config_path = recipe_dir / "config.toml"
    nodes_path = recipe_dir / "nodes.py"
    (recipe_dir / "results").mkdir(exist_ok=True)
    return (
        OptimizeResult,
        catena,
        config_path,
        minimize,
        mo,
        nodes_path,
        np,
        plt,
        recipe_dir,
        xr,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Calibrating SPLASH against COSMOS-UK soil moisture

    This recipe calibrates the `max_soil_moisture` parameter of the SPLASH water-balance model against daily soil moisture from a [COSMOS-UK](https://cosmos.ceh.ac.uk) site,
    first by minimising a misfit with scipy, then by sampling a posterior with the Metropolis-Hastings algorithm.
    The site's own meteorology drives the model.

    The recipe is a directory, [`recipes/soil_moisture`](https://github.com/SatTerC/viresco/tree/main/recipes/soil_moisture):

    | File | Contents |
    |---|---|
    | `config.toml` | The pipeline, from the COSMOS-UK file to SPLASH's soil moisture |
    | `nodes.py` | The nodes that turn COSMOS-UK's measurements into SPLASH's forcing |
    | `data/cosmos.nc` | Two years of daily data at Chimney Meadows, a lowland grassland site in Oxfordshire, taking in the dry summer of 2022, downloaded with [xharvest](https://nerc-ceh.github.io/xharvest/) |
    | `demo.py` | This notebook |

    To run it, download the directory, or clone the repository, and open the notebook with [marimo](https://marimo.io):

    ```sh
    git clone https://github.com/SatTerC/viresco.git
    marimo edit --sandbox viresco/recipes/soil_moisture/demo.py
    ```

    /// tip | From a terminal
    These commands made `data/cosmos.nc`, with xharvest's command-line tool;
    [My first pipeline](my_first_pipeline.md) says how to install it.
    To try another site or period, change `CHIMN` and the dates in both commands; `fetch` names each file `<site>_1D_<start>_<end>.json`.

    ```sh
    xharvest cosmos fetch CHIMN --start 2021-01-01 --end 2022-12-31 \
      --parameter cosmos_vwc --parameter precip --parameter snow \
      --parameter swin --parameter ta --out data/raw
    xharvest cosmos standardise data/raw/CHIMN_1D_20210101_20221231.json --out data/cosmos.nc
    ```
    ///

    The COSMOS-UK data is under the [Open Government Licence](http://www.nationalarchives.gov.uk/doc/open-government-licence);
    the [xharvest docs](https://nerc-ceh.github.io/xharvest/providers/cosmos-uk/#citing-the-data) say how to cite it.
    """)
    return


@app.cell(hide_code=True)
def _(config_path, mo):
    mo.md(f"""
    ## The pipeline

    xharvest writes a netCDF file that catena reads as it is, on its own `time` and `site` dimensions,
    since viresco's models take whatever dimension names the data has.

    - `[inputs.cosmos]` keeps the file's variable names, with `suffix = ""`.
    - `[inputs.site]` binds `latitude` and `elevation`, which are per-site coordinates of the file rather than variables; `vars` reads them just the same.
    - `[soil_moisture_nodes]` imports `nodes.py`, below, and sets the value `max_soil_moisture` takes until the calibration overrides it.
    - `[splash]` sets `sunshine_fraction_method = "shortwave"`, so SPLASH recovers the sunshine fraction it needs from measured shortwave radiation.
    - `[cosmos]` has no `_import_path`: xharvest registers its nodes under that section name, so catena finds
      [`cosmos_vwc_snow_masked`](https://nerc-ceh.github.io/xharvest/providers/cosmos-uk/#xharvest.cosmos.nodes.cosmos_vwc_snow_masked),
      which drops the days when snow on the ground corrupts the COSMOS signal.

    ```toml
    {config_path.read_text()}
    ```
    """)
    return


@app.cell(hide_code=True)
def _(mo, nodes_path):
    mo.md(rf"""
    ## The nodes

    Each node turns one COSMOS-UK variable into a gap-free SPLASH input in the unit SPLASH declares.
    COSMOS-UK does not measure sunshine fraction, so `shortwave_radiation` supplies the shortwave radiation SPLASH recovers it from;
    the [SPLASH page](../models/splash.md) explains how.
    Every unit the nodes declare is checked against the file and against SPLASH when the DAG is built, before anything runs.

    ```python
    {nodes_path.read_text()}
    ```
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The DAG
    """)
    return


@app.cell
def _(catena, config_path):
    catena.build_graph(config_path)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Validate, then run
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


@app.cell
def _(catena, config_path, mo, recipe_dir):
    run = catena.run(config_path)

    mo.md(
        f"Completed in {run.elapsed:.2f}s, writing "
        + ", ".join(f"`{out.path.relative_to(recipe_dir)}`" for out in run.written)
        + "."
    )
    return (run,)


@app.cell
def _(run):
    # @output: results
    results = run.outputs["soil_moisture"].isel(site=0)
    dates = results.indexes["time"]
    observations = results["cosmos_vwc_snow_masked"].values
    default_soil_moisture = results["soil_moisture"].values
    n_observed = int(results["cosmos_vwc_snow_masked"].count())
    results
    return dates, default_soil_moisture, n_observed, observations


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Observations

    The observations are COSMOS-UK's daily volumetric water content, with snow days masked out by xharvest's node.
    Against them is SPLASH's soil moisture with the starting value of `max_soil_moisture`.
    """)
    return


@app.cell
def _(catena, config_path):
    config = catena.load_config(config_path)
    default_max_soil_moisture = config.driver_config["initial_max_soil_moisture"]
    return config, default_max_soil_moisture


@app.cell
def _(dates, default_max_soil_moisture, default_soil_moisture, observations, plt):
    # @output: fig-observations
    _fig, _ax = plt.subplots(figsize=(12, 4))
    _ax.plot(dates, observations, color="k", lw=1, label="Observations")
    _ax.set_ylabel("COSMOS volumetric water content (%)")
    _twin = _ax.twinx()
    _twin.plot(
        dates,
        default_soil_moisture,
        color="tab:blue",
        lw=1,
        label=f"SPLASH, max_soil_moisture = {default_max_soil_moisture:.0f} mm",
    )
    _twin.set_ylabel("SPLASH soil moisture (mm)", color="tab:blue")
    _fig.legend(loc="lower left", bbox_to_anchor=(0.06, 0.12))
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Running the pipeline from Python

    The calibration runs SPLASH hundreds of times with different values of `max_soil_moisture`.
    It builds the pipeline's driver once, and passes each trial value as an override of the `max_soil_moisture` node,
    so nothing upstream of SPLASH is computed again.
    """)
    return


@app.cell
def _(catena, config, xr):
    driver = catena.build_driver(
        modules=config.modules,
        config=config.driver_config,
        node_specs=config.node_specs,
        base=config.base,
        registered=config.registered_modules,
    )
    inputs = catena.load_inputs(config.input_specs)
    forcing = driver.execute(
        ["sunshine_fraction", "precipitation", "temperature"],
        inputs=inputs,
    )

    def simulate(max_soil_moisture):
        """Run SPLASH with a uniform ``max_soil_moisture``, returning the one site."""
        capacity = xr.DataArray(float(max_soil_moisture), attrs={"units": "mm"})
        outputs = driver.execute(
            ["soil_moisture"],
            inputs=inputs,
            overrides={**forcing, "max_soil_moisture": capacity},
        )
        return outputs["soil_moisture"].isel(site=0).values

    return (simulate,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The objective function

    SPLASH's soil moisture $W$ is the plant-available water in a bucket of capacity $W_m$ (`max_soil_moisture`), in millimetres.
    A COSMOS probe sees the volumetric water content $\theta$ of the top 10-30 cm of soil,
    which never drains to zero and whose sensing depth varies with wetness.
    Rather than assume a depth and a residual water content, we let the data choose a linear map between the two,
    $\theta \approx a + b\,W$,
    fitting $a$ and $b$ by least squares for each trial value of $W_m$.
    What is left to calibrate is the *shape* of the soil moisture curve,
    which $W_m$ controls through when the bucket overflows and how fast it can supply evaporation.

    The objective is the mean squared residual of that fit, over the days with an observation.
    """)
    return


@app.cell
def _(np, observations, simulate):
    def fit_linear_map(modelled):
        """Fit ``observations ≈ a + b * modelled`` on the observed days.

        Returns the coefficients ``(a, b)`` and the mean squared residual.
        """
        observed = ~np.isnan(observations)
        design = np.column_stack([np.ones(observed.sum()), modelled[observed]])
        coefficients, *_ = np.linalg.lstsq(design, observations[observed])
        residuals = observations[observed] - design @ coefficients
        return coefficients, np.mean(residuals**2)

    def objective_function(params):
        return fit_linear_map(simulate(params[0]))[1]

    return fit_linear_map, objective_function


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Parameter optimisation
    """)
    return


@app.cell
def _(OptimizeResult, minimize, objective_function):
    prior_low, prior_high = 50.0, 500.0
    optimisation_history = []

    def logging_callback(intermediate_result: OptimizeResult) -> None:
        """A Callback to log the parameters and objective function at each iteration."""
        optimisation_history.append(
            [float(intermediate_result.x[0]), intermediate_result.fun]
        )

    optimisation_result = minimize(
        fun=objective_function,
        x0=[100.0],
        method="Nelder-Mead",
        bounds=[(prior_low, prior_high)],
        callback=logging_callback,
        options={"xatol": 0.01, "fatol": 1e-6, "maxiter": 200},
    )
    return optimisation_history, optimisation_result, prior_high, prior_low


@app.cell
def _(np, optimisation_history, plt):
    # @output: fig-optim
    _x, _f = np.array(optimisation_history).T

    _fig, _axes = plt.subplots(1, 2, figsize=(12, 4))

    _axes[0].plot(_f, marker="o")
    _axes[0].set_xlabel("Iteration")
    _axes[0].set_ylabel("Mean squared residual")
    _axes[0].set_title("Objective Function Convergence")
    _axes[0].grid(True)

    _axes[1].plot(_x, marker="o")
    _axes[1].set_xlabel("Iteration")
    _axes[1].set_ylabel("max_soil_moisture (mm)")
    _axes[1].set_title("Parameter Evolution")
    _axes[1].grid(True)

    _fig.tight_layout()
    _fig
    return


@app.cell
def _(fit_linear_map, mo, optimisation_result, simulate):
    best_max_soil_moisture = float(optimisation_result.x[0])
    best_modelled = simulate(best_max_soil_moisture)
    (best_a, best_b), _ = fit_linear_map(best_modelled)

    mo.md(
        "### Optimisation results\n\n"
        f"**Optimised max_soil_moisture:** {best_max_soil_moisture:.2f} mm\n\n"
        f"**Linear map:** a = {best_a:.3g}, b = {best_b:.3g}\n\n"
        f"**Mean squared residual:** {optimisation_result.fun:.4g}"
    )
    return best_a, best_b, best_max_soil_moisture, best_modelled


@app.cell
def _(
    best_a,
    best_b,
    best_max_soil_moisture,
    best_modelled,
    dates,
    observations,
    plt,
):
    # @output: fig-fit
    _fig, _ax = plt.subplots(figsize=(12, 4))
    _ax.plot(dates, observations, color="k", lw=1, label="Observations")
    _ax.plot(
        dates,
        best_a + best_b * best_modelled,
        color="tab:orange",
        lw=1.5,
        label=f"a + b·W, max_soil_moisture = {best_max_soil_moisture:.0f} mm",
    )
    _ax.set_ylabel("COSMOS volumetric water content (%)")
    _ax.set_title("Calibrated fit")
    _ax.legend()
    _ax.grid(True)
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## Bayesian inference

    A single point estimate says nothing about how well the data constrain $W_m$.
    Here we use the Metropolis-Hastings algorithm to sample a *distribution* over plausible values.

    The likelihood is Gaussian, with its standard deviation σ set to the root mean squared residual at the optimum,
    and the prior is uniform over the bounds the optimiser searched.
    With a uniform prior the posterior is proportional to the likelihood alone, p(θ|y) ∝ p(y|θ),
    so the posterior mode coincides with the optimum.

    The proposal step comes from the Laplace approximation: the curvature of the log posterior at the optimum,
    by finite differences, gives the width of a Gaussian approximation to the posterior.

    This treats every day's residual as independent.
    Real residuals are strongly autocorrelated, since a wet spell the model misses stays missed for days,
    so this posterior is narrower than the data justify.
    """)
    return


@app.cell
def _(np, objective_function):
    def make_log_posterior(
        prior_low: float,
        prior_high: float,
        likelihood_sigma: float,
        n_observed: int,
    ):
        π = np.pi
        σ = likelihood_sigma
        N = n_observed

        def log_likelihood(params):
            """Logarithm of a Gaussian likelihood function."""
            mse = objective_function(params)
            return -(N / (2 * σ**2)) * mse - (N / 2) * np.log(2 * π * σ**2)

        def log_prior(params):
            if prior_low <= params[0] <= prior_high:
                return 0.0
            return -np.inf

        def log_posterior(params):
            lp = log_prior(params)
            if np.isneginf(lp):
                return lp
            return lp + log_likelihood(params)

        return log_posterior

    return (make_log_posterior,)


@app.cell
def _(
    best_max_soil_moisture,
    make_log_posterior,
    n_observed,
    np,
    optimisation_result,
    prior_high,
    prior_low,
):
    log_posterior = make_log_posterior(
        prior_low=prior_low,
        prior_high=prior_high,
        likelihood_sigma=float(np.sqrt(optimisation_result.fun)),
        n_observed=n_observed,
    )

    # Laplace approximation: posterior standard deviation from the curvature at the mode.
    _h = 0.02 * best_max_soil_moisture
    _lp = [log_posterior([best_max_soil_moisture + k * _h]) for k in (-1, 0, 1)]
    _curvature = (_lp[0] - 2 * _lp[1] + _lp[2]) / _h**2
    laplace_sd = float(1 / np.sqrt(-_curvature))
    laplace_sd
    return laplace_sd, log_posterior


@app.cell
def _(best_max_soil_moisture, laplace_sd, log_posterior, np):
    # @output: acceptance
    _rng = np.random.default_rng(0)
    step_size = 2 * laplace_sd
    n_iterations = 200
    burn_in = 100

    # Warm-start from the optimum
    current = best_max_soil_moisture
    mcmc_history = [current]
    accepted = 0
    current_log_post = log_posterior([current])

    for i in range(burn_in + n_iterations):
        proposed = current + _rng.uniform(-step_size, step_size)

        proposed_log_post = log_posterior([proposed])
        log_acceptance_prob = proposed_log_post - current_log_post

        if np.log(_rng.uniform()) < log_acceptance_prob:
            current = proposed
            current_log_post = proposed_log_post

            if i >= burn_in:
                accepted += 1

        mcmc_history.append(current)

    acceptance_rate = accepted / n_iterations

    print(acceptance_rate)
    return burn_in, mcmc_history


@app.cell
def _(best_max_soil_moisture, burn_in, laplace_sd, mcmc_history, np, plt):
    # @output: fig-mcmc
    posterior_samples = mcmc_history[burn_in:]

    _fig, _axes = plt.subplots(1, 2, figsize=(12, 4))

    _axes[0].plot(mcmc_history)
    _axes[0].axvline(x=burn_in, color="r", linestyle="--", label=f"Burn-in ({burn_in})")
    _axes[0].set_xlabel("Iteration")
    _axes[0].set_ylabel("max_soil_moisture (mm)")
    _axes[0].set_title("MCMC History")
    _axes[0].grid(True)
    _axes[0].legend()

    _axes[1].hist(
        posterior_samples, bins=20, density=True, alpha=0.7, label="Posterior samples"
    )
    _x = np.linspace(min(posterior_samples), max(posterior_samples), 100)
    _axes[1].plot(
        _x,
        np.exp(-0.5 * ((_x - best_max_soil_moisture) / laplace_sd) ** 2)
        / (laplace_sd * np.sqrt(2 * np.pi)),
        "k--",
        label="Laplace approximation",
    )
    _axes[1].set_xlabel("max_soil_moisture (mm)")
    _axes[1].set_ylabel("Density")
    _axes[1].set_title("Posterior Distribution")
    _axes[1].grid(True)
    _axes[1].legend()

    _fig.tight_layout()
    _fig
    return


if __name__ == "__main__":
    app.run()
