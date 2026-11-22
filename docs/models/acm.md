---
title: ACM
icon: lucide/leaf
---

# Aggregated Canopy Model (ACM)

## Overview

ACM predicts daily gross primary productivity (GPP) of a whole canopy from a handful of drivers available at daily and regional scales.[^williams1997]
It was built as an emulator of a multilayer soil–plant–atmosphere model of half-hourly canopy processes: ten parameters were fitted so that ACM reproduced that model's daily GPP over a wide range of LAI, foliar nitrogen, temperature, irradiance, CO2, canopy height and soil water.
Without refitting, it then predicted measured GPP at Harvard Forest, at wet-sedge tundra sites at Toolik Lake, Alaska, and along a transect of Oregon conifer forests.

Viresco implements version 1, as published by Williams et al. (1997).
The later variants used in DALEC and CARDAMOM differ in structure as well as parameters, and are not reproduced here.

ACM carries no state from one day to the next: each day's GPP depends only on that day's drivers.
LAI is an observed input, so ACM needs no vegetation model upstream, and its GPP can drive [SGAM](sgam.md) through the weekly resampling `viresco setup` writes.

Having no state, ACM is not one node but four, split where the later variants of ACM differ from version 1:

| Node | Computes | Paper |
|------|----------|-------|
| `acm_nitrogen_limited_capacity` | photosynthetic capacity limited by canopy nitrogen and temperature | eq. 2 |
| `acm_canopy_conductance` | canopy conductance to CO2 | eq. 5 |
| `acm_seasonal_factor` | the seasonal correction, from `days_from_midsummer` | eq. 9 |
| `acm` | internal CO2, co-limitation by light, and GPP | eqs. 3, 4 and 6–9 |

A variant that changes one of the first three, as the ACM used in DALEC does all three, replaces that node and keeps the rest.
Every intermediate node can be written out like any other, which helps in diagnosing a fit.

The DAG for a pipeline running ACM alone, with nodes coloured by declared frequency (`D` for daily):

<div class="model-graph">
--8<-- "docs/models/_graphs/acm.svg"
</div>

## Theory

Equation numbers are those of the paper; symbols are as in its Table 2, and the settings below give each one's name in the config.

The daily mean temperature $T$ and half-range $D_T$ come from the daily extremes, $T = (T_\max + T_\min)/2$ and $D_T = (T_\max - T_\min)/2$.

**Nitrogen-limited capacity.** Canopy photosynthetic capacity is proportional to total canopy nitrogen, foliar nitrogen $N$ times LAI $L$, with an exponential temperature response:

$$
p_N = a_1 N L \, e^{a_2 T} \tag{2}
$$

**Canopy conductance** increases with the soil–leaf water potential difference $\Psi_d$ (negative, in MPa) and falls with temperature, canopy height $H$ and temperature range:

$$
g_c = \frac{-\Psi_d \, e^{b_1 T}}{b_2 H + D_T} \tag{5}
$$

**Internal CO2.** Metabolic supply, $p_N (C_i - \theta)/(k + C_i - \theta)$, and diffusive supply, $p_D = g_c (C_a - C_i)$, are assumed equal, which gives the internal CO2 concentration from the ambient $C_a$:

$$
C_i = \tfrac{1}{2}\left[C_a + q - p + \sqrt{(C_a + q - p)^2 - 4(C_a q - p\theta)}\right], \quad q = \theta - k, \quad p = p_N / g_c \tag{6}
$$

and the CO2-limited rate $p_D$ follows from eq. 4.

**Light.** The CO2-limited rate is co-limited by daily irradiance $I$ (MJ m-2 d-1) through a canopy quantum yield that saturates with LAI:

$$
p_I = \frac{E_0 I p_D}{E_0 I + p_D}, \quad E_0 = \frac{c_1 L^2}{c_2 + L^2} \tag{7, 8}
$$

**Day-of-year correction.** Daily irradiance already carries most of the effect of latitude and season, but GPP responds nonlinearly to it, so long days are more productive than short ones with the same total.
A linear correction in the number of days from midsummer, $D_{ms}$, gives the GPP:

$$
P_T = p_I (d_1 D_{ms} + d_2) \tag{9}
$$

### Where viresco departs from the paper

- **Days from midsummer** is computed by the `days_from_midsummer` node, around the calendar, from the solstice of the cell's hemisphere: day 173 in the north, as in the paper, and day 355 in the south, which the paper does not cover.
  Because the distance wraps around the year, 31 December is 173 days from the northern midsummer rather than the 192 the paper's $|173 - \text{day}|$ gives; the two agree up to day 355.
- **The tropics.** The paper sets $D_{ms} = 80$ "within the tropics"; viresco does so for $|\text{latitude}| < 23.44°$.
- **Irradiance** is read as daily mean shortwave radiation in W m-2, the unit viresco's other nodes use, and converted to a daily total in MJ m-2 inside the node.
- **Zero LAI** gives zero GPP, where the equations give $0/0$.
- **Frost.** For the Oregon transect the paper set GPP to zero on days below −2 °C. That is part of the application, not the model, and is not applied.

### Validity

The parameters were fitted over the driver ranges of the paper's Table 1: LAI 0.5–8, foliar N 1–4 g m-2, mean temperature 7–30 °C, half-range 1–12 °C, $C_a$ 250–750 ppm, $\Psi_d$ −0.5 to −4 MPa, canopy height 0.5–50 m, latitude 0–70° N and days of year 173–365.
GPP below 1 g m-2 d-1 was excluded from the fit.
Outside those ranges ACM extrapolates, and the authors found it underpredicts below an LAI of about 2.

`tests/test_acm.py` checks viresco's implementation against the paper's predictions for the six Toolik Lake plots (its Table 5 and Fig. 3).

## Usage

### Quickstart

ACM needs only meteorology, observed LAI and latitude, so it runs on its own:

```sh
viresco setup --models acm --defaults
viresco data-gen config.toml --grid 1 1 --duration 1y --seed 42
viresco run config.toml
```

The [quickstart](../guides/quickstart.md) walks through what each of those does, and how to point the config at your own data instead of the synthetic set.

### Configuration

The calibrated parameters default to the paper's Table 2.
Foliar nitrogen, canopy height and the water potential difference describe the site, and default to Harvard Forest (the paper's Table 4); set them for yours.
All of them go in the one `[acm]` section, whichever node takes them:

```toml
[acm]
acm_foliar_nitrogen = 1.92
acm_canopy_height = 24.0
acm_water_potential_difference = -2.5
```

#### `acm_nitrogen_limited_capacity` { #settings-acm_nitrogen_limited_capacity }

::: viresco.models.acm.acm_nitrogen_limited_capacity
    options:
      show_root_heading: false
      show_root_full_path: false
      show_root_toc_entry: false
      show_signature: false
      separate_signature: false
      show_docstring_returns: false
      show_docstring_raises: false
      show_docstring_description: false
      show_docstring_parameters: false
      heading_level: 4
      docstring_section_style: spacy

#### `acm_canopy_conductance` { #settings-acm_canopy_conductance }

::: viresco.models.acm.acm_canopy_conductance
    options:
      show_root_heading: false
      show_root_full_path: false
      show_root_toc_entry: false
      show_signature: false
      separate_signature: false
      show_docstring_returns: false
      show_docstring_raises: false
      show_docstring_description: false
      show_docstring_parameters: false
      heading_level: 4
      docstring_section_style: spacy

#### `acm_seasonal_factor` { #settings-acm_seasonal_factor }

::: viresco.models.acm.acm_seasonal_factor
    options:
      show_root_heading: false
      show_root_full_path: false
      show_root_toc_entry: false
      show_signature: false
      separate_signature: false
      show_docstring_returns: false
      show_docstring_raises: false
      show_docstring_description: false
      show_docstring_parameters: false
      heading_level: 4
      docstring_section_style: spacy

#### `acm` { #settings-acm }

::: viresco.models.acm.acm
    options:
      show_root_heading: false
      show_root_full_path: false
      show_root_toc_entry: false
      show_signature: false
      separate_signature: false
      show_docstring_returns: false
      show_docstring_raises: false
      show_docstring_description: false
      show_docstring_parameters: false
      heading_level: 4
      docstring_section_style: spacy

### Inputs

`latitude` is read from a file, as a variable or a coordinate; see [Inputs on a grid](index.md#inputs-on-a-grid).
`days_from_midsummer` takes `lai_obs` only for its daily calendar.

::: viresco.models.acm.days_from_midsummer
    options:
      show_root_heading: true
      show_root_full_path: false
      show_root_toc_entry: false
      show_signature: false
      separate_signature: false
      show_docstring_returns: true
      show_docstring_raises: false
      show_docstring_other_parameters: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.models.acm.acm_nitrogen_limited_capacity
    options:
      show_root_heading: true
      show_root_full_path: false
      show_root_toc_entry: false
      show_signature: false
      separate_signature: false
      show_docstring_returns: true
      show_docstring_raises: false
      show_docstring_other_parameters: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.models.acm.acm_canopy_conductance
    options:
      show_root_heading: true
      show_root_full_path: false
      show_root_toc_entry: false
      show_signature: false
      separate_signature: false
      show_docstring_returns: true
      show_docstring_raises: false
      show_docstring_other_parameters: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.models.acm.acm_seasonal_factor
    options:
      show_root_heading: true
      show_root_full_path: false
      show_root_toc_entry: false
      show_signature: false
      separate_signature: false
      show_docstring_returns: true
      show_docstring_raises: false
      show_docstring_other_parameters: false
      heading_level: 4
      docstring_section_style: spacy

::: viresco.models.acm.acm
    options:
      show_root_heading: true
      show_root_full_path: false
      show_root_toc_entry: false
      show_signature: false
      separate_signature: false
      show_docstring_returns: false
      show_docstring_raises: false
      show_docstring_other_parameters: false
      heading_level: 4
      docstring_section_style: spacy

### Outputs

The intermediate nodes above can be listed as outputs too, in the units their tables give.

::: viresco.models.acm.AcmOut
    options:
      show_root_heading: false
      show_root_toc_entry: false
      show_docstring_description: false
      docstring_section_style: spacy
      show_bases: false
      members: false

### Python API

See the [API documentation](../reference/modules/viresco.models/acm.md) for full function signatures and parameter details.

## References

[^williams1997]: Williams, M., Rastetter, E. B., Fernandes, D. N., Goulden, M. L., Shaver, G. R., and Johnson, L. C.: Predicting gross primary productivity in terrestrial ecosystems, Ecological Applications, 7, 882–894, 1997.
