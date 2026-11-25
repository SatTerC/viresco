---
title: Installation
icon: lucide/download
---

# Installation

Viresco is not on PyPI, so install it from GitHub.


## Prerequisites

- **Python 3.13** or later

## Install into an existing project

```sh
uv add git+https://github.com/NERC-CEH/viresco
```

This installs the latest `main`.
To install a specific release, append its tag to the URL, e.g. `git+https://github.com/NERC-CEH/viresco@v0.8.0`.

It installs the `viresco` package and the `viresco` CLI command into your environment, along with everything needed to run the built-in models.
That is [catena][catena], which provides the config parser, the DAG, contract validation, I/O and the `run`, `graph` and `subset` commands, plus its visualisation support, and the model libraries `pyrealm`, `rothc-py` and `sgam`.

There are no extras to choose from.
Viresco is pre-alpha and used by a handful of people, so a single install that always works is worth more than a smaller one.

## Install for development

```sh
git clone https://github.com/NERC-CEH/viresco.git
cd viresco
uv sync
source .venv/bin/activate
```

`uv sync` adds the development tooling on top of the runtime dependencies.

## System dependencies

### Graphviz (for pipeline visualisation)

The Python `graphviz` bindings come with the install, but `catena graph` also needs the Graphviz system binaries:

```sh
# Ubuntu/Debian
sudo apt install graphviz

# macOS
brew install graphviz
```

## Verify installation

```sh
catena --version
python -c "import viresco; print(viresco.__version__)"
```

These print the installed versions of catena and Viresco.

[catena]: https://github.com/NERC-CEH/catena
