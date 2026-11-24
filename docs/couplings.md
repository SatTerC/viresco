---
title: Couplings
icon: lucide/cable
---

# Couplings

No model knows the others exist.
Two connect only where a name and its units line up, and between viresco's models they mostly do not: the P-model reports GPP as pyrealm's flux in µg m⁻² s⁻¹, and SGAM wants a daily rate in g m⁻² d⁻¹.
A coupling makes one model's output into a node another consumes, and says why the conversion is what it is.

Each is selected by a key named for the node it produces, in the `[couplings]` section:

```toml
[couplings]
gpp_from = "pmodel"
lue_from = "pmodel"
volumetric_water_content_from = "splash"
soil_carbon_input_monthly_from = "sgam"
```

No coupling is on until its key is set, so enabling the section adds nothing by itself.
A coupling acts at its source's frequency, and a coarser consumer takes means or totals of it by `[[resample]]`: the P-model's GPP is converted daily, and SGAM reads its weekly mean.
`catena init` sets none of these keys: set one wherever one chosen model's output supplies another's input, as `recipes/config.toml` does. `ppfd_from` is best left unset, since SPLASH's estimate of light from sunshine fraction is no substitute for measured radiation.

A coupling with a physical constant in it takes the constant as a setting, under the same section.

--8<-- "docs_tools/_generated/couplings.md"

## The couplings

::: viresco.couplings.volumetric_water_content__splash
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 3
      docstring_section_style: spacy

::: viresco.couplings.aridity_index__splash
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 3
      docstring_section_style: spacy

::: viresco.couplings.ppfd__splash
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 3
      docstring_section_style: spacy

::: viresco.couplings.gpp__pmodel
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 3
      docstring_section_style: spacy

::: viresco.couplings.lue__pmodel
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 3
      docstring_section_style: spacy

::: viresco.couplings.soil_carbon_input_monthly__sgam
    options:
      show_root_full_path: false
      separate_signature: false
      heading_level: 3
      docstring_section_style: spacy

## Python API

See the [API documentation](reference/modules/viresco.couplings.md).
