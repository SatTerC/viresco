"""Stand-alone nodes that belong to no single model.

Each module is named for what it does, and is a catena module of its own, so a
pipeline enables one with a section of that name (``[humidity]``). These build
model inputs from what datasets actually distribute: VPD from humidity, PPFD
from shortwave radiation, pressure from elevation, and daily series from coarser
ones. See ``docs/adr/0001-node-names-and-module-frequency.md`` for why they live
here rather than in a model.
"""

from . import humidity, interpolate, pressure, radiation

__all__ = ["humidity", "interpolate", "pressure", "radiation"]
