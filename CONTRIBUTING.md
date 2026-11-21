# Contributing

Viresco is in alpha, and breaking changes to the config schema, the Python API and behaviour are made freely rather than behind compatibility shims.

## What lives where

Viresco is a thin domain package on [catena](https://github.com/NERC-CEH/catena), which owns the framework: config parsing, the DAG, contract validation, I/O, caching, blocking, subsetting and the `run`, `graph` and `subset` commands.
Viresco supplies the model and node modules, the `setup` and `data-gen` commands, and the documentation of the science.

A change that would be useful to a pipeline that is not about carbon probably belongs in catena.

The design decisions behind viresco are recorded in [`docs/adr/`](docs/adr/).

## Development setup

You need Python 3.13, [uv](https://docs.astral.sh/uv/getting-started/installation/) and [just](https://github.com/casey/just).

```sh
git clone https://github.com/SatTerC/viresco.git
cd viresco
uv sync
source .venv/bin/activate
uv run pre-commit install
```

The pre-commit hooks run `uv-lock`, pyright and ruff, not the test suite.

## Common tasks

```sh
just              # lint, type check and test
just test         # the test suite
just lint         # format and lint with ruff, check the recipe notebooks with marimo
just typecheck    # pyright
just docs         # render the model graphs and build the docs with zensical
just export <x>   # render recipe notebook <x> into docs/recipes/
just export-all   # render the quickstart and every documented recipe
```

## Adding a model or node

Read [Contributing a model](docs/contributing/models.md).
Open an issue describing the model before writing code.

## Documentation

The docs are markdown built with [zensical](https://zensical.org/), not Sphinx.
The tables of a model's inputs, outputs and settings are rendered from its signatures and docstrings, so change the docstring rather than the page.
`just docs` builds the site into `site/`.

## Pull requests

- One change per pull request.
- Add tests for new behaviour, and run `just` before opening it.
- Update the documentation the change affects.
- A design decision too large for a commit message goes in `docs/adr/`.
