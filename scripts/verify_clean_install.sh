#!/usr/bin/env bash
# Verify the documented autodev install works on a "clean environment": a
# fresh virtualenv, installing from a built wheel (not an editable checkout
# import), invoked from a temp directory outside the repo so no relative
# import or CWD-dependent path can accidentally make the test pass (E34-S1-T3).
#
# Usage: scripts/verify_clean_install.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

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

echo "==> Running from a clean cwd outside the repo checkout"
cd "$WORKDIR"

echo "==> autodev --version"
autodev --version

echo "==> autodev config validate --profile local"
autodev config validate --profile local

echo "==> Clean-environment install verified."
