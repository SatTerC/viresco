"""The modules viresco registers with catena.

The ``catena.modules`` entry points in ``pyproject.toml`` are the one list of
viresco's model, driver and coupling modules. Everything else that
enumerates them reads it from here, or is checked against it by
``tests/test_registry.py``, so registering a module is one line in
``pyproject.toml`` (and a ``uv sync``, which is what refreshes the installed
entry points).
"""

from importlib import import_module
from importlib.metadata import entry_points
from types import ModuleType

__all__ = [
    "COUPLINGS",
    "DRIVERS",
    "KINDS",
    "MODELS",
    "import_all",
    "import_registered",
    "registered",
]

#: Package holding the model modules: one per process model.
MODELS = "viresco.models"
#: Package holding the driver modules: forcing variables derived from data.
DRIVERS = "viresco.drivers"
#: The one coupling module: model outputs into other models' inputs.
COUPLINGS = "viresco.couplings"
#: Where each kind of registered module lives: a package of modules, or, for
#: `COUPLINGS`, the module itself.
KINDS = (MODELS, DRIVERS, COUPLINGS)


def registered(package: str) -> dict[str, str]:
    """Return the section name and module path of each module ``package`` holds.

    Parameters
    ----------
    package
        `MODELS`, `DRIVERS` or `COUPLINGS`.

    Returns
    -------
    dict[str, str]
        Section name to module path, sorted by name.
    """
    found = {
        ep.name: ep.value
        for ep in entry_points(group="catena.modules")
        if ep.value == package or ep.value.startswith(f"{package}.")
    }
    return dict(sorted(found.items()))


def import_registered(package: str) -> dict[str, ModuleType]:
    """Return each module `registered` lists for ``package``, imported."""
    return {name: import_module(path) for name, path in registered(package).items()}


def import_all() -> dict[str, ModuleType]:
    """Return every module registered from any of `KINDS`, imported."""
    return {
        name: module
        for package in KINDS
        for name, module in import_registered(package).items()
    }
