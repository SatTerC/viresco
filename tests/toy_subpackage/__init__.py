"""A model written as a subpackage, for the tests only.

Its node is defined in a submodule and exported here, as a larger model's would
be. The conformance and frequency tests check it alongside the registered
modules, so a check that looked only at functions defined in a module's own file
would find no node here and fail.
"""

from ._model import ToyOut, toy

__all__ = ["ToyOut", "toy"]
