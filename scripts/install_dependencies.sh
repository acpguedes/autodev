#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
NODE_BIN="${NODE_BIN:-npm}"

printf '\n[1/4] Creating Python virtual environment at %s\n' "$VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

printf '\n[2/4] Installing backend dependencies\n'
pip install --upgrade pip
pip install -r "$ROOT_DIR/backend/requirements.txt"

printf '\n[3/4] Installing frontend dependencies\n'
cd "$ROOT_DIR/frontend"
"$NODE_BIN" install

printf '\n[4/4] Done\n'
printf 'Backend venv: %s\n' "$VENV_DIR"
printf 'Run backend with: source %s/bin/activate && uvicorn backend.api.main:app --reload\n' "$VENV_DIR"
printf 'Run frontend with: cd %s/frontend && %s run dev\n' "$ROOT_DIR" "$NODE_BIN"
