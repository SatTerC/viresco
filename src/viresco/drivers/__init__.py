"""Drivers: forcing variables derived from what datasets distribute.

A driver computes one quantity from data, and its variants differ only in which
data they start from: VPD from dewpoint, specific humidity or relative humidity.
None consumes a model's output; a node that does is a coupling. Each module is
named for a variable family and is a catena module of its own, so a pipeline
enables one with a section of that name (``[humidity]``). See
``docs/adr/0003-component-kinds.md``.
"""

from . import humidity, interpolate, pressure, radiation

__all__ = ["humidity", "interpolate", "pressure", "radiation"]
