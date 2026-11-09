"""Render one model's DAG to an SVG for its documentation page.

The `viresco graph` command visualises a whole pipeline, so this builds the
smallest config that exercises a single model — the model's own section plus
the inputs and outputs `viresco.scaffold.config_gen` infers for it — and graphs
that. The I/O paths in the generated config are never opened: building the
graph reads the DAG's contracts, not the data.

Going through the CLI rather than catena's Python API is deliberate. The graph
internals moved module between conduit 0.2.0 and catena 0.4.0, whereas the
command has stayed put, and `AGENTS.md` records `graph` as one of the commands
catena owns.

Run through ``just graph <model>``; the SVG is committed, like the exported
example notebooks.
"""

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

import tomlkit

from viresco.scaffold.config_gen import generate_config

#: Placeholder I/O paths. `generate_config` requires them; nothing reads them.
PATHS = {
    "inputs_daily": "inputs/daily.nc",
    "inputs_weekly": "inputs/weekly.nc",
    "inputs_monthly": "inputs/monthly.nc",
    "inputs_static": "inputs/static.nc",
    "outputs_daily": "outputs/daily.nc",
    "outputs_weekly": "outputs/weekly.nc",
    "outputs_monthly": "outputs/monthly.nc",
}


def render(model: str) -> str:
    """Return the SVG source for ``model``'s DAG."""
    config = generate_config(builtin_models=[model], custom_modules=[], paths=PATHS)

    with tempfile.TemporaryDirectory() as tmp:
        config_file = Path(tmp) / f"{model}.toml"
        config_file.write_text(tomlkit.dumps(config._data))
        stem = Path(tmp) / model
        subprocess.run(
            ["viresco", "graph", str(config_file), "-o", str(stem)],
            check=True,
            capture_output=True,
        )
        source = stem.with_suffix(".dot")
        source.write_text(_drop_config_notes(source.read_text()))
        dot = subprocess.run(
            ["dot", "-Tsvg", str(source)],
            check=True,
            capture_output=True,
        )
    return dot.stdout.decode()


def _drop_config_notes(dot: str) -> str:
    """Remove Hamilton's floating config-value boxes.

    catena moves each config value a node consumes into that node's config
    table, so the boxes left floating are config no node reads, such as
    ``hamilton.enable_power_user_mode``. The tables and the legend's config
    entry are kept.
    """
    return "".join(
        line
        for line in dot.splitlines(keepends=True)
        if not ("shape=note" in line and "[label=<<b>" in line)
    )


def as_inline_html(svg: str) -> str:
    """Strip the SVG down to something markdown will pass through untouched.

    The XML prolog and doctype go because the fragment is inlined into a page
    rather than served as a document. The fixed ``width``/``height`` go too, so
    the ``viewBox`` scales the drawing to its container. A blank line anywhere
    inside would end the raw-HTML block and leave the remainder as literal
    text, so those are collapsed as well.
    """
    svg = svg[svg.index("<svg") :]
    svg = re.sub(r'<svg width="[^"]*" height="[^"]*"', "<svg", svg, count=1)
    return re.sub(r"\n\s*\n+", "\n", svg).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Model name, e.g. 'splash'.")
    parser.add_argument("output", type=Path, help="Destination .svg path.")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(as_inline_html(render(args.model)) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
