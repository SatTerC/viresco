"""Carbon-cycle model modules for catena pipelines.

Each module here is an ordinary catena "bring your own module": a set of plain
functions whose names are node names and whose parameter names are upstream node
names, with units and frequency contracts declared on the signatures.

viresco registers all of them under catena's ``catena.modules`` entry-point
group, so a config names one by its section alone and needs no
``_import_path``::

    [rothc]
    rothc_spinup_years = 1

The section name is the module name: ``acm``, ``splash``, ``pmodel``, ``sgam``
and ``rothc``.
"""

from . import acm, pmodel, rothc, sgam, splash

__all__ = ["acm", "pmodel", "rothc", "sgam", "splash"]
