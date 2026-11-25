---
title: RothC
icon: lucide/worm
---

# Rothamsted Carbon model (RothC)


## Overview

RothC simulates the turnover of soil organic carbon (SOC) in non-waterlogged soils ([Jenkinson, 1990](https://doi.org/10.1098/rstb.1990.0177)). It splits SOC into five distinct compartments – four active and one inert – and accounts for soil type (clay content), temperature, moisture, and plant cover to calculate decay rates.

The five pools are:

| Pool | Name | Description |
|------|------|-------------|
| DPM | Decomposable Plant Material | Easily decomposed organic matter |
| RPM | Resistant Plant Material | More slowly decomposed organic matter |
| BIO | Microbial Biomass | Living microbial biomass |
| HUM | Humified Organic Matter | Stable humus |
| IOM | Inert Organic Matter | Chemically inert, does not decompose |

We forked the Python implementation from [Rothamsted Research](https://github.com/Rothamsted-Models/RothC_Py/), repackaged it for pip installation and made it ~20× faster. Our fork is available at [github.com/SatTerC/RothC_Py](https://github.com/SatTerC/RothC_Py).

The DAG for a pipeline running RothC alone, with nodes coloured by declared frequency (`1ME` for monthly):

--8<-- "docs_tools/_generated/graphs/rothc.html"

--8<-- "docs_tools/_generated/guides/rothc.md"

## Theory

Carbon turnover follows first-order kinetics, where each active pool $k$ evolves according to:

$$
\frac{dC_k}{dt} = I_k - k_k \cdot C_k
$$

where $C_k$ is the carbon content of pool $k$, $I_k$ is the carbon input to that pool, and $k_k$ is the decomposition rate constant, modified by temperature, moisture, and soil cover factors.

The decomposition rates are scaled by:

- **Temperature rate modifier** – increases with temperature
- **Moisture rate modifier** – depends on the ratio of rainfall to evaporation
- **Soil cover factor** – reduces decomposition when soil is covered by vegetation

### Spin-up

RothC requires initial pool sizes to begin simulation. A spin-up phase runs the model over repeated climate cycles until the pools reach equilibrium, which fixes the initial conditions.

For full model details, see:

- [SatTerC RothC_Py documentation](https://satterc.github.io/RothC_Py/science.html)
- [Original model description paper](https://github.com/Rothamsted-Models/RothC_Py/blob/main/RothC_description.pdf) (Coleman, Prout and Milne, Rothamsted Research)

## Details

### Evapotranspiration, not open-pan evaporation

RothC's own water-balance driver is open-pan evaporation, which the underlying RothC_Py scales by 0.75 to get evapotranspiration.
Viresco instead supplies potential evapotranspiration directly, since SPLASH computes it (Priestley-Taylor) on its way to AET.
There is nothing to convert, so `evap_factor` defaults to 1.0.

PET, not AET, is the right driver: RothC's water balance is rainfall minus evaporative *demand*, and AET is already suppressed by the soil dryness RothC is itself computing, so feeding AET in double-counts the water limitation and holds the soil systematically too wet.

### Input-building nodes

Three of RothC's monthly inputs, `plant_cover_monthly`, `dpm_rpm_ratio_monthly` and `farmyard_manure_input_monthly`, are built by this module from per-cell static data rather than loaded.
Static data has no calendar, so each also takes `temperature_monthly`, read only for its time coordinate.
If you supply your own version of one of these nodes, it needs a time-bearing input for the same reason.

### Other sources of inputs

- `inert_organic_matter` is read as data unless `inert_organic_matter_from = "falloon"` is set.
  The node `inert_organic_matter__falloon` then derives it from `organic_carbon_stocks`, total soil organic carbon, as $\text{IOM} = 0.049\,\text{SOC}^{1.139}$ ([Falloon et al., 1998](https://doi.org/10.1016/S0038-0717(97)00256-3)).
- `soil_carbon_input_monthly` can come from SGAM's litter pool, by the coupling `soil_carbon_input_monthly__sgam`, selected by `soil_carbon_input_monthly_from = "sgam"`; see [Couplings](../couplings.md).

## Reference

--8<-- "docs_tools/_generated/reference/rothc.md"
