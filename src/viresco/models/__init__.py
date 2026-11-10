"""Carbon-cycle model modules for catena pipelines.

Each module here is an ordinary catena "bring your own module": a set of plain
functions whose names are node names and whose parameter names are upstream node
names, with units and frequency contracts declared on the signatures.

viresco registers all of them under catena's ``catena.modules`` entry-point
group, so a config names one by its section alone and needs no
``_import_path``::

    [rothc]
    n_years_spinup = 1

The section name is the module name: ``splash``, ``pmodel``, ``sgam``,
``rothc``, and ``shared``, which holds the nodes that belong to no one model
because they do not run at that model's frequency.
"""

from . import pmodel, rothc, sgam, shared, splash

__all__ = ["pmodel", "rothc", "sgam", "shared", "splash"]
