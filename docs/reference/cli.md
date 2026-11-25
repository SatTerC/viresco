---
title: CLI
icon: lucide/square-terminal
---

# CLI

viresco has no command of its own: pipelines are written, checked and run with [catena's CLI][catena-cli], which installs with viresco.
viresco registers its models, drivers and couplings with catena, so a config names one by its section alone (`[splash]`), and `catena init` offers them.

```sh
catena init -m splash          # write a starting config
catena run config.toml --dry-run
catena run config.toml
catena graph --png config.toml
```

`catena init` lists the inputs the chosen models need and nothing among them produces, and each model's settings at their defaults.
It does not add the `[[resample]]` entries or `[couplings]` keys that join models at different frequencies; write those by hand, following [`recipes/config.toml`](https://github.com/NERC-CEH/viresco/blob/main/recipes/config.toml).
Its file paths are placeholders, to be set before the pipeline runs.

See [catena's CLI reference][catena-cli] for every command and option, and [scale up][catena-scale] for `catena subset`.

[catena-cli]: https://nerc-ceh.github.io/catena/reference/cli.html
[catena-scale]: https://nerc-ceh.github.io/catena/guides/run/scale-up.html
