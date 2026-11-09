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
# ukceh-viresco = { path = ".." }
# # TODO: pin to a catena release tag once catena and viresco stop changing in step.
# ukceh-catena = { git = "https://github.com/NERC-CEH/catena", branch = "main" }
# xharvest = { git = "https://github.com/NERC-CEH/xharvest", branch = "main" }
# ///

import marimo

__generated_with = "0.23.5"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Calibrating SPLASH against COSMOS-UK soil moisture

    This notebook calibrates the `max_soil_moisture` parameter of the SPLASH water-balance model,
    first by minimising a misfit with scipy, then by sampling a posterior with the Metropolis-Hastings algorithm.

    By default the observations are real: daily soil moisture from a [COSMOS-UK](https://cosmos.ceh.ac.uk) site,
    downloaded and standardised by [xharvest](https://github.com/NERC-CEH/xharvest),
    with the site's own meteorology driving the model.
    xharvest writes a netCDF file that catena reads as it is, and registers catena nodes of its own,
    so the whole path from the provider's API to the model is a single pipeline config.

    Pass `--data synthetic` to swap in synthetic inputs, and observations generated from a known parameter value,
    as a check that the calibration recovers that value:

    ```sh
    uv run soil_moisture.py --data synthetic
    marimo edit soil_moisture.py -- --data synthetic
    ```
    """)
    return


@app.cell
def _():
    import tempfile
    import textwrap
    import tomllib
    from datetime import date
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import xarray as xr
    from catena import build_driver, load_inputs
    from catena.config import Config
    from scipy.optimize import OptimizeResult, minimize
    from xharvest import cosmos

    from viresco.scaffold.data_gen import generate_synthetic_data

    return (
        Config,
        OptimizeResult,
        Path,
        build_driver,
        cosmos,
        date,
        generate_synthetic_data,
        load_inputs,
        minimize,
        mo,
        np,
        plt,
        tempfile,
        textwrap,
        tomllib,
        xr,
    )


@app.cell
def _(mo):
    data_source = mo.cli_args().get("data", "cosmos")
    if data_source not in ("cosmos", "synthetic"):
        raise ValueError(
            f"--data must be 'cosmos' or 'synthetic', not {data_source!r}."
        )
    synthetic = data_source == "synthetic"
    mo.md(f"Data source: **{data_source}**")
    return (synthetic,)


@app.cell(hide_code=True)
def _(mo, synthetic):
    mo.md(
        r"""
    ## Pipeline configuration

    The synthetic config is minimal: daily climate and static inputs straight into `[splash]`.
    """
        if synthetic
        else r"""
    ## Pipeline configuration

    COSMOS-UK measures most of what SPLASH needs, but under its own names and units, and on a `site` dimension.
    The config reads xharvest's standardised file with `suffix = ""`, so its variables keep their names,
    and adapts them to SPLASH with `[[node]]` entries:

    - Each SPLASH input is renamed onto viresco's `pixel` dimension.
    - `latitude` and `elevation` come from the file's per-site coordinates.
    - Daily precipitation totals (`mm`) are restated as a rate (`mm d-1`), with gaps filled with zero.
      Gaps in temperature and shortwave radiation are filled by linear interpolation.
      SPLASH carries soil moisture over from one day to the next, so it refuses any gap.
    - COSMOS-UK does not measure sunshine fraction $s_f$.
      It is recovered from incoming shortwave radiation $R_s$ by inverting SPLASH's own transmissivity model,
      $R_s / R_a = (0.25 + 0.5\,s_f)(1 + 2.67\times10^{-5} z)$,
      with the extraterrestrial radiation $R_a$ from FAO-56 (Allen et al., 1998, eqs. 21-25).
    - `max_soil_moisture` is a placeholder, overridden on every run of the calibration.

    `[cosmos]` has no `_import_path`: xharvest registers its nodes under that section name, so catena finds
    [`cosmos_vwc_snow_masked`](https://nerc-ceh.github.io/xharvest/providers/cosmos-uk/#xharvest.cosmos.nodes.cosmos_vwc_snow_masked),
    which drops the days when snow on the ground corrupts the COSMOS signal.
    Every unit declared along the way is checked when the DAG is built, before anything runs.
    """
    )
    return


@app.cell
def _(synthetic, textwrap):
    synthetic_config_toml = textwrap.dedent("""\
    [splash]
    soil_moisture_init_max_iter = 50

    [inputs.daily]
    path = "daily.nc"
    vars = [
      "precipitation",
      "sunshine_fraction",
      "temperature",
    ]

    [inputs.static]
    path = "static.nc"
    suffix = ""
    vars = [
      "elevation",
      "max_soil_moisture",
    ]
    """)

    cosmos_config_toml = textwrap.dedent('''\
    [splash]
    soil_moisture_init_max_iter = 50

    [cosmos]

    [inputs.cosmos]
    path = "cosmos.nc"
    suffix = ""
    vars = ["cosmos_vwc", "precip", "snow", "swin", "ta"]

    [[node]]
    name = "latitude"
    inputs = ["ta"]
    expression = "ta.lat.rename(site='pixel')"
    units = "degrees"

    [[node]]
    name = "elevation"
    inputs = ["ta"]
    expression = "ta.altitude.rename(site='pixel')"
    units = "m"

    [[node]]
    name = "max_soil_moisture"
    inputs = ["elevation"]
    expression = "xr.full_like(elevation, 150.0)"
    units = "mm"
    overwrite_units = true

    [[node]]
    name = "temperature_daily"
    inputs = ["ta"]
    expression = "ta.interpolate_na('time').rename(site='pixel')"
    units = "degC"

    [[node]]
    name = "precipitation_daily"
    inputs = ["precip"]
    expression = "precip.fillna(0).rename(site='pixel')"
    units = "mm d-1"
    overwrite_units = true

    [[node]]
    name = "solar_declination_daily"
    inputs = ["swin"]
    expression = "0.409 * xr.ufuncs.sin(2 * 3.141592653589793 / 365 * swin.time.dt.dayofyear - 1.39)"
    units = "rad"

    [[node]]
    name = "extraterrestrial_shortwave_daily"
    inputs = ["latitude", "solar_declination_daily"]
    expression = """(
        lambda φ, δ: 37.586
        * (1 + 0.033 * xr.ufuncs.cos(2 * 3.141592653589793 / 365 * δ.time.dt.dayofyear))
        * (lambda ω: ω * xr.ufuncs.sin(φ) * xr.ufuncs.sin(δ) + xr.ufuncs.cos(φ) * xr.ufuncs.cos(δ) * xr.ufuncs.sin(ω))(
            xr.ufuncs.arccos(-xr.ufuncs.tan(φ) * xr.ufuncs.tan(δ))
        )
    )(xr.ufuncs.deg2rad(latitude), solar_declination_daily)"""
    units = "MJ m-2 d-1"

    [[node]]
    name = "sunshine_fraction_daily"
    inputs = ["swin", "extraterrestrial_shortwave_daily", "elevation"]
    expression = """(
        (
            swin.interpolate_na('time').rename(site='pixel')
            / extraterrestrial_shortwave_daily
            / (1 + 2.67e-5 * elevation)
            - 0.25
        ) / 0.5
    ).clip(0, 1)"""
    units = "1"
    overwrite_units = true
    ''')

    config_toml = synthetic_config_toml if synthetic else cosmos_config_toml
    return (config_toml,)


@app.cell
def _(Config, config_toml, mo, tomllib):
    # @output: config
    parsed_config = Config(tomllib.loads(config_toml)).parse()
    mo.md("```toml\n" + config_toml + "```")
    return (parsed_config,)


@app.cell(hide_code=True)
def _(mo, synthetic):
    mo.md(
        r"""
    ## Input data

    `generate_synthetic_data` writes two years of daily inputs for a single pixel.
    """
        if synthetic
        else r"""
    ## Downloading COSMOS-UK data

    Two years at Chimney Meadows, a lowland grassland site in Oxfordshire, taking in the dry summer of 2022.
    Change the site or the dates here; `cosmos.sites()` lists every site and its period of record.

    `cosmos.fetch` skips a download it has already made, so re-running the notebook does not fetch again.
    The data is under the [Open Government Licence](http://www.nationalarchives.gov.uk/doc/open-government-licence);
    the [xharvest docs](https://nerc-ceh.github.io/xharvest/providers/cosmos-uk/#citing-the-data) say how to cite it.
    """
    )
    return


@app.cell
def _(
    Path,
    cosmos,
    date,
    generate_synthetic_data,
    load_inputs,
    mo,
    parsed_config,
    synthetic,
    tempfile,
):
    if synthetic:
        _workdir = Path(tempfile.mkdtemp())
        parsed_config.input_specs["daily"].path = str(_workdir / "daily.nc")
        parsed_config.input_specs["static"].path = str(_workdir / "static.nc")
        generate_synthetic_data(config=parsed_config, grid=(1, 1), n_days=730, seed=42)
    else:
        _site = "CHIMN"
        _data_dir = mo.notebook_dir() / "data"
        _raw = cosmos.fetch(
            _site,
            date(2021, 1, 1),
            date(2022, 12, 31),
            _data_dir / "cosmos_raw",
            parameters=["cosmos_vwc", "precip", "snow", "swin", "ta"],
        )
        parsed_config.input_specs["cosmos"].path = str(
            cosmos.to_netcdf(_raw, _data_dir / f"cosmos_{_site}.nc")
        )

    inputs = load_inputs(parsed_config.input_specs)
    return (inputs,)


@app.cell
def _(build_driver, parsed_config):
    dr = build_driver(
        modules=parsed_config.modules,
        config=parsed_config.driver_config,
        node_specs=parsed_config.node_specs,
        registered=parsed_config.registered_modules,
    )
    return (dr,)


@app.cell(hide_code=True)
def _(mo, synthetic):
    mo.md(
        r"""
    ## Observations

    As a check that the calibration works, we generate synthetic 'observations' by running the model
    with the default parameter value and adding Gaussian noise with a standard deviation of 5 mm.
    """
        if synthetic
        else r"""
    ## Observations

    The observations are COSMOS-UK's daily volumetric water content, with snow days masked out by xharvest's node.
    """
    )
    return


@app.cell
def _(dr, inputs, np, synthetic):
    _outputs = dr.execute(["max_soil_moisture", "soil_moisture_daily"], inputs=inputs)
    default_max_soil_moisture = float(_outputs["max_soil_moisture"].values[0])
    default_soil_moisture = _outputs["soil_moisture_daily"]
    n_pixels = default_soil_moisture.sizes["pixel"]

    if synthetic:
        _rng = np.random.default_rng(42)
        true_max_soil_moisture = default_max_soil_moisture
        observations = default_soil_moisture.values[:, 0] + _rng.normal(
            0, 5, default_soil_moisture.sizes["time"]
        )
        observations_label = "Synthetic soil moisture (mm)"
    else:
        true_max_soil_moisture = None
        observations = dr.execute(["cosmos_vwc_snow_masked"], inputs=inputs)[
            "cosmos_vwc_snow_masked"
        ].values[:, 0]
        observations_label = "COSMOS volumetric water content (%)"

    n_observed = int(np.count_nonzero(~np.isnan(observations)))
    return (
        default_max_soil_moisture,
        default_soil_moisture,
        n_observed,
        n_pixels,
        observations,
        observations_label,
        true_max_soil_moisture,
    )


@app.cell
def _(
    default_max_soil_moisture,
    default_soil_moisture,
    observations,
    observations_label,
    plt,
):
    # @output: fig-observations
    _time = default_soil_moisture["time"].values
    _fig, _ax = plt.subplots(figsize=(12, 4))
    _ax.plot(_time, observations, color="k", lw=1, label="Observations")
    _ax.set_ylabel(observations_label)
    _twin = _ax.twinx()
    _twin.plot(
        _time,
        default_soil_moisture.values[:, 0],
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
    The synthetic observations are in millimetres already, so there the fit finds $a \approx 0$ and $b \approx 1$.
    """)
    return


@app.cell
def _(np, xr):
    def simulate(max_soil_moisture, dr, n_pixels, inputs):
        """Run SPLASH with a uniform ``max_soil_moisture`` and return the first pixel."""
        max_sm_grid = xr.DataArray(
            np.full(n_pixels, max_soil_moisture), dims=["pixel"], attrs={"units": "mm"}
        )
        outputs = dr.execute(
            final_vars=["soil_moisture_daily"],
            overrides={"max_soil_moisture": max_sm_grid},
            inputs=inputs,
        )
        return outputs["soil_moisture_daily"].values[:, 0]

    def fit_linear_map(modelled, observations):
        """Fit ``observations ≈ a + b * modelled`` on the observed days.

        Returns the coefficients ``(a, b)`` and the mean squared residual.
        """
        observed = ~np.isnan(observations)
        design = np.column_stack([np.ones(observed.sum()), modelled[observed]])
        coefficients, *_ = np.linalg.lstsq(design, observations[observed])
        residuals = observations[observed] - design @ coefficients
        return coefficients, np.mean(residuals**2)

    def objective_function(params, dr, observations, n_pixels, inputs):
        modelled = simulate(params[0], dr, n_pixels, inputs)
        return fit_linear_map(modelled, observations)[1]

    return fit_linear_map, objective_function, simulate


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Parameter optimisation
    """)
    return


@app.cell
def _(
    OptimizeResult,
    dr,
    inputs,
    minimize,
    n_pixels,
    objective_function,
    observations,
):
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
        args=(dr, observations, n_pixels, inputs),
        method="Nelder-Mead",
        bounds=[(prior_low, prior_high)],
        callback=logging_callback,
        options={"xatol": 0.01, "fatol": 1e-6, "maxiter": 200},
    )
    return optimisation_history, optimisation_result, prior_high, prior_low


@app.cell
def _(np, optimisation_history, plt, synthetic, true_max_soil_moisture):
    # @output: fig-optim
    _x, _f = np.array(optimisation_history).T

    _fig, _axes = plt.subplots(1, 2, figsize=(12, 4))

    _axes[0].plot(_f, marker="o")
    if synthetic:
        _axes[0].axhline(
            y=25, color="k", linestyle="--", alpha=0.6, label="Noise variance (σ²=25)"
        )
        _axes[0].legend()
    _axes[0].set_xlabel("Iteration")
    _axes[0].set_ylabel("Mean squared residual")
    _axes[0].set_title("Objective Function Convergence")
    _axes[0].grid(True)

    _axes[1].plot(_x, marker="o")
    if synthetic:
        _axes[1].axhline(
            y=true_max_soil_moisture,
            color="r",
            linestyle="--",
            label=f"True value ({true_max_soil_moisture:.1f})",
        )
        _axes[1].legend()
    _axes[1].set_xlabel("Iteration")
    _axes[1].set_ylabel("max_soil_moisture (mm)")
    _axes[1].set_title("Parameter Evolution")
    _axes[1].grid(True)

    _fig.tight_layout()
    _fig
    return


@app.cell
def _(
    dr,
    fit_linear_map,
    inputs,
    mo,
    n_pixels,
    observations,
    optimisation_result,
    simulate,
    synthetic,
    true_max_soil_moisture,
):
    best_max_soil_moisture = float(optimisation_result.x[0])
    best_modelled = simulate(best_max_soil_moisture, dr, n_pixels, inputs)
    (best_a, best_b), _ = fit_linear_map(best_modelled, observations)

    mo.md(
        "### Optimisation results\n\n"
        + (
            f"**True max_soil_moisture:** {true_max_soil_moisture:.2f} mm\n\n"
            if synthetic
            else ""
        )
        + f"**Optimised max_soil_moisture:** {best_max_soil_moisture:.2f} mm\n\n"
        + f"**Linear map:** a = {best_a:.3g}, b = {best_b:.3g}\n\n"
        + f"**Mean squared residual:** {optimisation_result.fun:.4g}"
    )
    return best_a, best_b, best_max_soil_moisture, best_modelled


@app.cell
def _(
    best_a,
    best_b,
    best_max_soil_moisture,
    best_modelled,
    default_soil_moisture,
    observations,
    observations_label,
    plt,
):
    # @output: fig-fit
    _time = default_soil_moisture["time"].values
    _fig, _ax = plt.subplots(figsize=(12, 4))
    _ax.plot(_time, observations, color="k", lw=1, label="Observations")
    _ax.plot(
        _time,
        best_a + best_b * best_modelled,
        color="tab:orange",
        lw=1.5,
        label=f"a + b·W, max_soil_moisture = {best_max_soil_moisture:.0f} mm",
    )
    _ax.set_ylabel(observations_label)
    _ax.set_title("Calibrated fit")
    _ax.legend()
    _ax.grid(True)
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo, synthetic):
    mo.md(
        r"""
    ---

    ## Bayesian inference

    Two features of the optimisation results are worth noting before we proceed:

    - **The objective does not converge to zero.** Its irreducible minimum is about σ² = 25,
      the variance of the noise added to the synthetic observations.
      Even with the exact true parameter, the model cannot fit the noise away.
    - **The optimum is not exactly the true value.** With a finite, noisy sample the optimiser finds the
      parameter that best explains the *noisy* signal, not the true one.
      This bias shrinks with more data but never vanishes.

    This motivates Bayesian inference: rather than a single point estimate, we want a *distribution* over
    plausible parameter values that honestly reflects the residual uncertainty.
    Here we use the Metropolis-Hastings algorithm.
    """
        if synthetic
        else r"""
    ---

    ## Bayesian inference

    A single point estimate says nothing about how well the data constrain $W_m$.
    Here we use the Metropolis-Hastings algorithm to sample a *distribution* over plausible values.
    """
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The likelihood is Gaussian, with its standard deviation σ set to the root mean squared residual at the optimum,
    and the prior is uniform over the bounds the optimiser searched.
    With a uniform prior the posterior is proportional to the likelihood alone, p(θ|y) ∝ p(y|θ),
    so the posterior mode coincides with the optimum.

    The proposal step comes from the Laplace approximation: the curvature of the log posterior at the optimum,
    by finite differences, gives the width of a Gaussian approximation to the posterior.

    This treats every day's residual as independent.
    Real residuals are strongly autocorrelated, since a wet spell the model misses stays missed for days,
    so with real data this posterior is narrower than the data justify.
    """)
    return


@app.cell
def _(np, objective_function):
    def make_log_posterior(
        dr,
        observations,
        n_pixels,
        inputs,
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
            mse = objective_function(params, dr, observations, n_pixels, inputs)
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
    dr,
    inputs,
    make_log_posterior,
    n_observed,
    n_pixels,
    np,
    observations,
    optimisation_result,
    prior_high,
    prior_low,
):
    log_posterior = make_log_posterior(
        dr,
        observations,
        n_pixels,
        inputs,
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
def _(
    best_max_soil_moisture,
    burn_in,
    laplace_sd,
    mcmc_history,
    np,
    plt,
    synthetic,
    true_max_soil_moisture,
):
    # @output: fig-mcmc
    posterior_samples = mcmc_history[burn_in:]

    _fig, _axes = plt.subplots(1, 2, figsize=(12, 4))

    _axes[0].plot(mcmc_history)
    _axes[0].axvline(x=burn_in, color="r", linestyle="--", label=f"Burn-in ({burn_in})")
    _axes[0].set_xlabel("Iteration")
    _axes[0].set_ylabel("max_soil_moisture (mm)")
    _axes[0].set_title("MCMC History")
    _axes[0].grid(True)

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

    if synthetic:
        _axes[0].axhline(
            y=true_max_soil_moisture,
            color="g",
            linestyle=":",
            label=f"True value ({true_max_soil_moisture:.1f})",
        )
        _axes[1].axvline(
            x=true_max_soil_moisture,
            color="g",
            linestyle=":",
            label=f"True value ({true_max_soil_moisture:.1f})",
        )
    _axes[0].legend()
    _axes[1].legend()

    _fig.tight_layout()
    _fig
    return


if __name__ == "__main__":
    app.run()
