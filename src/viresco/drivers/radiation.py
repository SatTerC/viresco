"""Photosynthetic photon flux density in the units the P-model takes.

The P-model wants ``ppfd`` as a mean photon flux over the day, in micromoles per
square metre per second. Datasets give downwelling shortwave radiation instead
(ERA5 ``ssrd``, CHESS-met ``rsds``), and SPLASH estimates a daily photon total
from sunshine fraction. This module derives ``ppfd`` from either.

The config key ``ppfd_from`` chooses the variant: ``"shortwave"`` (the default,
used when the key is unset) or ``"splash"``.
"""

from typing import Annotated

import xarray_annotated as xra
from hamilton.function_modifiers import config
from xarray import DataArray
from xarray_annotated import Unit, check_annotations, stamp_output_units

from ..temporal import DAILY


@config.when_not_in(ppfd_from=["splash"])
@check_annotations
@stamp_output_units(overwrite=True)
def ppfd__shortwave(
    shortwave_radiation: Annotated[DataArray, Unit("W m-2"), DAILY],
    *,
    par_fraction: float = 0.45,
    par_photons_per_mj: float = 4.57,
) -> Annotated[DataArray, Unit("umol m-2 s-1"), DAILY]:
    """PPFD from downwelling shortwave radiation.

    The PAR share of the shortwave energy, times the photon content of PAR. With
    the defaults that is about 2.06 micromoles of photons per joule of shortwave.

    Parameters
    ----------
    shortwave_radiation
        Daily mean downwelling shortwave radiation at the surface (watts per
        square metre). ERA5's ``ssrd`` is an accumulated energy in J m-2:
        divide a daily total by 86400 s before it reaches this node.

    Other Parameters
    ----------------
    par_fraction
        Fraction of shortwave energy in the photosynthetically active band,
        400-700 nm. Typically 0.45-0.50 at the surface.
    par_photons_per_mj
        Photon content of PAR (moles per megajoule, which is micromoles per
        joule). 4.57 is the standard value for the 400-700 nm band. The same
        constant, under the same name, bridges the P-model's LUE to SGAM's, so
        one setting serves both.
    """
    return shortwave_radiation * par_fraction * par_photons_per_mj


@config.when(ppfd_from="splash")
@check_annotations
@stamp_output_units(overwrite=True)
def ppfd__splash(
    estimated_ppfd: Annotated[DataArray, Unit("mol m-2 d-1"), DAILY],
) -> Annotated[DataArray, Unit("umol m-2 s-1"), DAILY]:
    """PPFD from SPLASH's daily photon total.

    A pure unit conversion: the daily total becomes the mean rate over the
    24-hour day. SPLASH estimates the radiation from sunshine fraction and
    latitude, so this needs no radiation input beyond what SPLASH already takes.

    Parameters
    ----------
    estimated_ppfd
        Daily total PPFD from `viresco.models.splash` (moles per square metre
        per day).
    """
    return xra.units.convert(estimated_ppfd, "umol m-2 s-1")
