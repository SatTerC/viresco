"""Generate stand-in inputs for the four-model pipeline.

The pipeline reads some twenty variables, so rather than write each one out this
uses viresco's synthetic-data generator, which knows a plausible range, unit and
seasonal shape for every model input. It writes each ``[inputs.*]`` file of
``config.toml`` to the path that section gives: two years on a 4 x 4 grid over
southern England. The data is deterministic, so the results are reproducible.

Run it directly, or call `write_inputs` from a notebook.
"""

from pathlib import Path

from catena import load_config

from viresco.scaffold.data_gen import generate_synthetic_data

CONFIG = Path(__file__).parent / "config.toml"


def write_inputs(config_path: Path = CONFIG) -> list[Path]:
    """Write every input file ``config_path`` reads, returning their paths."""
    config = load_config(config_path)
    paths = [Path(spec.path) for spec in config.input_specs.values()]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    generate_synthetic_data(config=config, grid=(4, 4), n_days=730, seed=42)
    return paths


if __name__ == "__main__":
    for path in write_inputs():
        print(path)
