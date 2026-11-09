"""Render one model's DAG to an SVG for its documentation page.

`catena.build_graph` visualises a whole pipeline, so this builds the smallest
config that exercises a single model — the model's own section plus the inputs
and outputs `viresco.scaffold.config_gen` infers for it — and graphs that. The
I/O paths in the generated config are never opened: building the graph reads
the DAG's contracts, not the data.

Run through ``just graph <model>``. The SVG is not committed: ``just docs``
regenerates every model's graph before each build.
"""

import argparse
import re
from pathlib import Path

from catena import build_graph

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
    return build_graph(config.parse()).pipe(format="svg", encoding="utf-8")


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
