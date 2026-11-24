"""Tooling for developers and the test suite: configs and data without real inputs.

`config_gen` writes a config for a chosen set of models, with the resamples and
couplings between them; `data_gen` fills a config's input files with synthetic
data. Users start a config with ``catena init`` instead.
"""

from .config_gen import (
    generate_config,
    get_builtin_models,
    get_model_config,
)

__all__ = [
    "generate_config",
    "get_builtin_models",
    "get_model_config",
]
