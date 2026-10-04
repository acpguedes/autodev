#!/usr/bin/env bash
# Verify the documented autodev install works on a "clean environment": a
# fresh virtualenv, installing from a built wheel (not an editable checkout
# import), invoked from a temp directory outside the repo so no relative
# import or CWD-dependent path can accidentally make the test pass (E34-S1-T3).
#
# E61-S3-T2 extends this to prove the global home (AUTODEV_HOME) is created
# and used independently of the launch directory, and that a second install
# over the first preserves its existing contents.
#
# Usage: scripts/verify_clean_install.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR" "$REPO_ROOT/backend/CHANGELOG.md" "$REPO_ROOT/backend/README.md"' EXIT

echo "==> Packaging CHANGELOG.md and README.md into backend/ (E61-S3-T1, see backend/pyproject.toml)"
cp "$REPO_ROOT/CHANGELOG.md" "$REPO_ROOT/backend/CHANGELOG.md"
cp "$REPO_ROOT/README.md" "$REPO_ROOT/backend/README.md"

echo "==> Building wheel from ${REPO_ROOT}/backend"
python -m pip install --quiet --upgrade build >/dev/null
python -m build --wheel --outdir "$WORKDIR/dist" "$REPO_ROOT/backend" >/dev/null

WHEEL="$(ls "$WORKDIR"/dist/*.whl)"
echo "==> Built: $(basename "$WHEEL")"

echo "==> Installing into a fresh venv (no repo on PYTHONPATH)"
python -m venv "$WORKDIR/venv"
# shellcheck disable=SC1091
source "$WORKDIR/venv/bin/activate"
pip install --quiet "$WHEEL"

echo "==> Running from a clean cwd outside the repo checkout, with an isolated global home"
cd "$WORKDIR"
export AUTODEV_HOME="$WORKDIR/autodev-home"

echo "==> autodev --version"
autodev --version

echo "==> autodev config validate --profile local"
autodev config validate --profile local

echo "==> autodev doctor (creates and uses the global home as a side effect of its global_home check)"
set +e
autodev doctor >/dev/null
set -e
[ -d "$AUTODEV_HOME" ] || { echo "AUTODEV_HOME was not created at $AUTODEV_HOME" >&2; exit 1; }

echo "==> Seeding the global home with a marker file and a global config"
echo "pre-existing-marker" > "$AUTODEV_HOME/marker.txt"
printf '{"llm": {"provider": "ollama"}}\n' > "$AUTODEV_HOME/autodev.config.json"

echo "==> Reinstalling the same wheel over the existing install"
pip install --quiet --force-reinstall --no-deps "$WHEEL"

echo "==> Verifying the global home's contents survived the reinstall"
[ -f "$AUTODEV_HOME/marker.txt" ] || { echo "AUTODEV_HOME contents were lost across reinstall" >&2; exit 1; }
autodev config show | grep -q '"provider": "ollama"' \
  || { echo "the global configuration layer did not survive reinstall" >&2; exit 1; }

echo "==> Clean-environment install verified, including AUTODEV_HOME preservation across reinstall."
