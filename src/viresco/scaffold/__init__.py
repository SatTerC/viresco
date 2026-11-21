"""Scaffolding: getting a runnable pipeline off the ground without real data.

`config_gen` writes a starting config from a chosen set of models, behind
``viresco setup``; `data_gen` fills that config's input files with synthetic
data, behind ``viresco data-gen``. Neither is needed once a pipeline has real
inputs — they exist so that it can be run, and tested, before it does.
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
