---
title: Splash
icon: lucide/droplet
---

# SPLASH model


## Overview

SPLASH (Simple Process-led Algorithms for Simulating Habitats) is a water balance model that estimates soil moisture, actual evapotranspiration (AET) and surface water runoff for sites ([Davis et al., 2017](https://doi.org/10.5194/gmd-10-689-2017)).

The model takes an initial estimate of soil moisture, then uses time series of precipitation, temperature and sunshine fraction to track how the daily water balance changes with incoming precipitation, condensation and AET. Soil moisture, temperature and downwelling solar radiation at the site all feed into AET and condensation, which is why the site's elevation and latitude are required inputs.

We wrap the [NumPy-based `pyrealm` implementation](https://github.com/ImperialCollegeLondon/pyrealm) of SPLASH.
The [pyrealm SPLASH documentation](https://pyrealm.readthedocs.io/en/latest/users/splash.html) is the authoritative source for the model theory.

The DAG for a pipeline running SPLASH alone, with nodes coloured by declared frequency (`D` for daily):

<div class="model-graph">
--8<-- "docs/models/_graphs/splash.svg"
</div>

--8<-- "docs_tools/_generated/guides/splash.md"

## Theory

The daily water balance equation is:

$$
W_{n[t]} = W_{n[t-1]} + P_{[t]} + C_{[t]} - \textrm{AET}_{[t]},
$$

where:

- $W_{n[t]}$ – current soil moisture (mm)
- $W_{n[t-1]}$ – previous day's soil moisture (mm)
- $P_{[t]}$ – precipitation (mm·d⁻¹)
- $C_{[t]}$ – condensation (mm·d⁻¹)
- $\textrm{AET}_{[t]}$ – actual evapotranspiration (mm·d⁻¹)

Runoff is whatever that balance leaves above the maximum soil moisture capacity ($W_m$), taken before the cap is applied:

$$
R_{[t]} = \max\left(W_{n[t]} - W_m,\; 0\right), \qquad W_{n[t]} \leftarrow \min\left(W_{n[t]}, W_m\right)
$$

The capacity also limits how fast the soil can supply water for evaporation, with supply rate $S_w = S_c W_{n[t-1]} / W_m$, where $S_c$ is 1.05 mm·h⁻¹.
$W_m$ comes from the required `max_soil_moisture` input, so it can vary per cell.

## Details

/// admonition | Results differ from pyrealm 2.0.0 called directly
    type: note

pyrealm 2.0.0 uses the configured capacity for runoff but a fixed 150 mm for the supply rate.
This wrapper applies the configured capacity to both, as the water balance under [Theory](#theory) and [Davis et al. (2017)](https://doi.org/10.5194/gmd-10-689-2017) specify, so its results differ from a direct pyrealm call wherever capacity is not 150 mm.
///

### Initial soil moisture estimation

SPLASH estimates initial soil moisture by iterating over a full year of climate data until the difference between year-start and year-end soil moisture falls below a threshold, so the run starts from a quasi-equilibrium state.
An input period shorter than a year cannot equilibrate and fails.

That tolerance is evaluated over the whole block, so results shift by ~1e-4 relative when the `[blocking]` block size or the `[subset]` range changes.
On a grid, both split the `y` dimension, so a block is a set of whole rows.

If any valid cell in a block has not converged within `soil_moisture_init_max_iter` iterations, the run stops with an error.

To start from a measured state, or to continue an earlier run, set `soil_moisture_init_method = "prescribed"` and supply `initial_soil_moisture`.
That skips the spin-up, so the year minimum and the dependence on block size no longer apply.

### Sunshine fraction from measured radiation

SPLASH works out all of its radiation from the sunshine fraction $s_f$: the shortwave reaching the ground as $\tau R_a$, with transmissivity $\tau = (0.25 + 0.5\,s_f)(1 + 2.67\times10^{-5} z)$ ([Linacre, 1968](https://doi.org/10.1016/0002-1571(68)90022-8)) and $R_a$ the radiation at the top of the atmosphere, and the net longwave from $s_f$ and temperature.
It has no way to take measured radiation instead.

Sites with a radiometer but no sunshine recorder, such as COSMOS-UK's, can set `sunshine_fraction_method = "shortwave"` and supply `shortwave_radiation`.
`sunshine_fraction` is then computed by inverting the transmissivity relation, with pyrealm's own $R_a$ and coefficients, so SPLASH's modelled shortwave reproduces the measurement.

Two things follow:

- The result is clipped to 0–1. A day whose transmissivity is below 0.25 clips to 0, and on it SPLASH's shortwave exceeds the measurement. Overcast days often fall there: at the COSMOS-UK site in Chimney Meadows, a third of November–February days do.
- Net longwave still comes from [Prentice et al. (1993)](https://doi.org/10.1016/0304-3800(93)90126-D), through the recovered $s_f$, so any longwave measurement goes unused.

### Missing values

Each cell's outcome comes from its own inputs, so it does not depend on the block size:

| Pixel | Example | Outcome |
|---|---|---|
| Masked | All climate inputs NaN, or a NaN in `elevation`, `latitude`, `max_soil_moisture` or `initial_soil_moisture` | NaN outputs, with no error or warning |
| Gap | Some climate values NaN, including one variable with no data while the others have some | The run stops with an error naming the cells |
| Model failure | Complete inputs, but pyrealm returns NaN | NaN outputs, with a warning naming the cells |

A gap stops the run because soil moisture carries over from one day to the next, so everything after it would be lost.
Fill gaps in a `[[node]]` before SPLASH, or mask the cell.

A misconfigured input that makes every climate variable NaN is indistinguishable from a masked block, so that run finishes with NaN outputs and no error.

Model failures come from pyrealm 2.0.0, whose AET calculation can return NaN at high latitudes.

The input dates must also be consecutive days, and a missing date stops the run with an error, because pyrealm steps through days by position.

## Reference

--8<-- "docs_tools/_generated/reference/splash.md"

### Inputs for other settings

The inputs above are those of the default settings.
Each subsection below applies only when its setting is configured.

#### Initial state, for `prescribed` initialisation

Required when `soil_moisture_init_method` is `prescribed`.

::: viresco.models.splash.soil_moisture_init_inputs__prescribed
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      show_root_heading: false
      show_root_toc_entry: false
      show_signature: false
      show_docstring_description: false
      show_docstring_returns: false
      docstring_section_style: spacy

#### Shortwave radiation, for `shortwave` sunshine fraction

Required, in place of `sunshine_fraction`, when `sunshine_fraction_method` is `shortwave`.

::: viresco.models.splash.sunshine_fraction__shortwave
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      show_root_heading: false
      show_root_toc_entry: false
      show_signature: false
      show_docstring_description: false
      show_docstring_returns: false
      docstring_section_style: spacy
      extra:
        hide_parameters: [elevation, latitude]
