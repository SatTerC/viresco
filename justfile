_: lint typecheck test

# Format and lint the package using ruff, and lint the recipe notebooks using marimo.
lint:
  ruff format
  ruff check --fix
  marimo check recipes/*/demo.py

# Variant of `lint` that doesn't cause any changes to files.
lint-check:
  ruff format --check
  ruff check
  marimo check recipes/*/demo.py

# Run static type checker.
typecheck:
  pyright

# Run the full test suite.
test:
  pytest --verbose # --log-cli-level=INFO

# Run tests with coverage report.
test-cov:
  pytest --cov=viresco --cov-report=term-missing --cov-fail-under=90

# Re-record the pyrealm unit anchor in tests/data/pyrealm_golden.json.
# Only after reviewing *why* pyrealm's output changed. If a unit convention
# moved, correct the annotation rather than the recorded numbers.
regen-pyrealm-golden:
  uv run python scripts/regen_pyrealm_golden.py

# Render a model's DAG to an SVG inlined by its docs page.
graph model:
  uv run python scripts/render_model_graph.py {{model}} docs/models/_graphs/{{model}}.svg

# Re-render every model graph in docs/models/_graphs/.
graph-all:
  just graph splash
  just graph pmodel
  just graph sgam
  just graph rothc

# Build the documentation using Zensical.
# Depends on `graph-all` because the model graphs are generated, not committed:
# rendering one takes well under a second, so there is nothing to gain by
# checking in an SVG that a signature change would silently invalidate.
# `--clean` because zensical's incremental cache does not track the files pulled
# in by `pymdownx.snippets`, so a freshly rendered graph is otherwise ignored.
# Does not depend on `export-all`, which takes minutes, but refuses to build
# while any recipe notebook lacks an export, since every link to it would break.
docs: graph-all
  @for r in {{documented_recipes}}; do md="docs/recipes/$r.md"; [ -f "$md" ] || { echo "error: $md is missing; run \`just export-all\` first" >&2; exit 1; }; done
  zensical build --clean

# The recipes published in the docs, which must match the Recipes nav in
# zensical.toml. The others still run in tests/test_recipes.py.
documented_recipes := "my_first_pipeline soil_moisture"

# Export a single recipe notebook to docs/recipes/.
# A recipe is a directory whose notebook is `recipes/<recipe>/demo.py`.
export recipe:
  # Export to Markdown and keep the HTML notebook in the generated assets directory.
  marimo-md-export "recipes/{{recipe}}/demo.py" \
    "docs/recipes/{{recipe}}.md" --keep-html --overflow scroll

# Export every documented recipe notebook to docs/recipes/.
export-all:
  @for r in {{documented_recipes}}; do just export "$r"; done

# Tag the version in pyproject.toml and push the tag.
tag:
  #!/usr/bin/env bash
  set -euo pipefail
  v=$(uv version --short)
  [[ $v != *dev* ]] || { echo "refusing to tag dev version $v" >&2; exit 1; }
  [[ $(git branch --show-current) == main ]] || { echo "not on main" >&2; exit 1; }
  git diff --quiet HEAD || { echo "uncommitted changes" >&2; exit 1; }
  stale=$(grep -L "\"ukceh-viresco==$v\"" recipes/*/demo.py || true)
  [[ -z $stale ]] || { echo "recipes not pinned to ukceh-viresco==$v:" $stale >&2; exit 1; }
  git fetch --quiet origin main
  [[ $(git rev-parse HEAD) == $(git rev-parse origin/main) ]] \
    || { echo "main differs from origin/main" >&2; exit 1; }
  git tag -a "v$v" -m "v$v"
  git push origin "v$v"

# Create a GitHub release for the tagged version, deploying the docs if stable.
release:
  #!/usr/bin/env bash
  set -euo pipefail
  v=$(uv version --short)
  git rev-parse --quiet --verify "refs/tags/v$v" >/dev/null \
    || { echo "no tag v$v: run 'just tag' first" >&2; exit 1; }
  pre=()
  [[ ! $v =~ (a|b|rc)[0-9]+$ ]] || pre=(--prerelease)
  gh release create "v$v" --verify-tag --generate-notes "${pre[@]}"
