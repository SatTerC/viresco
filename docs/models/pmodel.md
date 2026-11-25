---
title: P-model
icon: lucide/leaf
---

# P-model


## Overview

The P-model is an optimality-based light use efficiency model for simulating ecosystem gross primary production (GPP) ([Stocker et al., 2020](https://doi.org/10.5194/gmd-13-1545-2020)).
Rather than assigning fixed trait values to plant functional types (PFTs), it predicts how plants continuously acclimate to their environment based on eco-evolutionary optimality theory – the idea that plants adapt to maximise resource use efficiency ([Prentice et al., 2014](https://doi.org/10.1111/ele.12211)).
For a broader overview of the model's challenges and future directions, see [the University of Reading LEMONTREE blog](https://research.reading.ac.uk/lemontree/the-p-model-challenges-we-face-and-plan-to-address/).

The model rests on three hypotheses:

**Least-Cost Hypothesis** – Plants balance water loss during transpiration against carbon fixation capacity to minimise total cost.
This predicts how the ratio of leaf-internal to ambient CO₂ (χ) varies with environment: χ decreases in dry air (conserving water), increases in warm conditions (water transport becomes cheaper due to lower viscosity), and decreases at high altitude (lower O₂ makes photosynthesis cheaper) ([Prentice et al., 2014](https://doi.org/10.1111/ele.12211)).

**Coordination Hypothesis** – Plants adjust their photosynthetic capacity (Vcmax) to fully utilise available light, avoiding waste.
This yields a simple proportionality between photosynthetic capacity (at growth temperature) and incident light intensity.

**Cost-Benefit Hypothesis** – Leaves balance the cost of maintaining maximum electron transport rate (Jmax) against the benefit of electron-transport-limited photosynthesis, predicting the Jmax:Vcmax ratio ([Wang et al., 2017](https://doi.org/10.1038/s41477-017-0006-x)).

Together the three hypotheses let the P-model predict GPP without biome-specific calibration, from environmental drivers (light, temperature, CO₂, vapour pressure deficit, soil moisture) and fAPAR alone.

We wrap the [NumPy-based `pyrealm` implementation](https://github.com/ImperialCollegeLondon/pyrealm) of the P-model.
The [pyrealm P-model documentation](https://pyrealm.readthedocs.io/en/latest/users/pmodel/module_overview.html) is the authoritative source for the model theory.

Viresco runs the P-model daily.
pyrealm's standard `PModel` has no timestep: it computes each cell from that cell's drivers alone, assuming the plants have acclimated to them, so the frequency it runs at is the pipeline's choice.
Its rates (PPFD, GPP, Vcmax, Jmax) are per second, and stand for the mean over the day when the drivers are daily means.
A model wanting coarser values, such as weekly SGAM, takes means of the daily outputs.
Because the model is nonlinear, those are not the outputs of a run on weekly mean drivers.

The DAG for a pipeline running the P-model alone, with nodes coloured by declared frequency (`D` for daily):

<div class="model-graph">
--8<-- "docs/models/_graphs/pmodel.svg"
</div>

--8<-- "docs_tools/_generated/guides/pmodel.md"

## Theory

The P-model builds on the Farquhar–von Caemmerer–Berry (FvCB) model of C3 photosynthesis, which describes the instantaneous response of photosynthesis to environmental conditions.
The FvCB model expresses the net CO₂ assimilation rate $A$ as the minimum of two limiting rates:

$$A = \min(W_c, W_j) - R_d$$

where $W_c$ is the Rubisco-limited rate, $W_j$ is the electron-transport-limited rate, and $R_d$ is dark respiration.

### Key quantities

The FvCB model depends on several quantities:

- **$\Gamma^*$** – the photorespiratory CO₂ compensation point, which varies predictably with temperature and O₂ partial pressure
- **$K$** – the effective Michaelis–Menten coefficient of Rubisco, also temperature- and O₂-dependent
- **$\phi_0$** – the maximum light-use efficiency of photosynthesis (theoretical maximum ≈ 0.125, i.e., at least 8 photons per fixed carbon atom)

Three quantities are treated as unknowns that plants optimise:

- **$V_{\text{cmax}}$** – maximum CO₂ fixation capacity (Rubisco activity)
- **$J_{\text{max}}$** – maximum electron transport capacity
- **$\chi = c_i / c_a$** – the ratio of leaf-internal to ambient CO₂

### Optimal $\chi$ (least-cost hypothesis)

The least-cost hypothesis yields an expression for optimal $\chi$ that depends on temperature, vapour pressure deficit $D$, atmospheric pressure $p$, and the relative viscosity of water $\eta^*$:

$$\chi = \frac{\Gamma^*}{c_a} + \left(1 - \frac{\Gamma^*}{c_a}\right) \frac{\xi}{\xi + \sqrt{D \cdot \eta^*}}$$

where $\xi$ is a cost factor that depends on $p$ and $\eta^*$.
This formulation captures the observed responses: $\chi$ decreases with increasing VPD, increases with temperature (via $\eta^*$), and decreases with altitude (via $p$).

### Light use efficiency

Under the coordination hypothesis, $V_{\text{cmax}}$ is set so that $W_c = W_j$ at typical light levels.
Combined with the optimal $\chi$, this leads to a prediction of light use efficiency (LUE, denoted $\text{LUE}$ or $m$):

$$\text{LUE} = \frac{A}{\text{PPFD} \cdot f_{\text{APAR}}}$$

where PPFD is photosynthetic photon flux density and $f_{\text{APAR}}$ is the fraction of absorbed PAR.
GPP is then:

$$\text{GPP} = \text{LUE} \cdot \text{PPFD} \cdot f_{\text{APAR}}$$

### Soil moisture stress

The P-model includes a soil moisture stress factor $\beta(\theta)$ that reduces GPP under dry conditions.
The implementation in `pyrealm` uses the soil moisture parameter $\theta$ (volumetric water content) to modulate both $\chi$ and LUE.

## Details

### Soil moisture

In viresco, $\theta$ reaches `pyrealm` only with the `lavergne20` optimal $\chi$ methods; see [soil moisture inputs](#inputs-soil-moisture).

### Daily drivers

Every time-varying driver is daily.
Few datasets distribute them daily in these units: the [drivers](../drivers/index.md) derive VPD from humidity, PPFD from shortwave radiation or SPLASH, pressure from elevation, and daily fAPAR and CO₂ from composites and monthly records.

### Outputs for SGAM

SGAM consumes GPP, LUE and iWUE as weekly means, which `recipes/config.toml` makes with a `[[resample]]` entry.
GPP and LUE are not in the units SGAM consumes either.
The couplings `gpp__pmodel` and `lue__pmodel` convert the daily values, where the conversion factor is visible rather than buried in a wrapper; see [Couplings](../couplings.md).
iWUE needs no coupling, because `pyrealm` and SGAM agree on µmol mol⁻¹.

## Reference

--8<-- "docs_tools/_generated/reference/pmodel.md"

### Inputs for other methods

The inputs above are those of the default methods.
Each subsection below applies only when its method is configured, and a run without that method never asks for those inputs.

#### Soil moisture, for `lavergne20` optimal χ { #inputs-soil-moisture }

Required when `method_optchi` is `lavergne20_c3` or `lavergne20_c4`.

::: viresco.models.pmodel.optchi_inputs__theta
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

#### Root zone stress, for `rootzonestress` optimal χ

Required when `method_optchi` is `prentice14_rootzonestress`, `c4_rootzonestress` or `c4_no_gamma_rootzonestress`.

::: viresco.models.pmodel.optchi_inputs__rootzonestress
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

#### Climatology, for `sandoval` quantum yield

Required when `method_kphio = "sandoval"`.

::: viresco.models.pmodel.kphio_inputs__sandoval
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

The PET in `aridity_index` comes from [SPLASH](splash.md).
The coupling `aridity_index__splash`, selected by `aridity_index_from = "splash"`, derives it, rather than a wrapper hiding the choice of PET; see [Couplings](../couplings.md).
`mean_growth_temperature` is derived for you; see [below](#inputs-mean-growth-temperature).

#### Growth temperature, for `kattge_knorr` Arrhenius scaling

Required when `method_arrhenius = "kattge_knorr"`.
`mean_growth_temperature` is derived for you; see [below](#inputs-mean-growth-temperature).

::: viresco.models.pmodel.arrhenius_inputs__kattge_knorr
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

#### Mean growth temperature { #inputs-mean-growth-temperature }

`mean_growth_temperature` is not loaded but derived by this module from the daily temperature it already takes, so a run using `sandoval` or `kattge_knorr` needs no extra input for it.

::: viresco.models.pmodel.mean_growth_temperature
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 4
      show_root_heading: false
      show_root_toc_entry: false
      show_signature: false
      show_docstring_returns: false
      docstring_section_style: spacy
