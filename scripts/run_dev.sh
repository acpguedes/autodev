#!/usr/bin/env bash
# Start the AutoDev backend (FastAPI on :8000) and frontend (Next.js on
# :3000) together with prefixed log streams. Ctrl-C stops both; the first
# non-zero exit code is propagated. Invoked by `make run`.
set -euo pipefail
# Job control gives each background job its own process group, so the trap
# below can kill whole trees (npm -> next, uvicorn -> reloader workers) with
# a single negative-PID kill instead of orphaning grandchildren.
set -m

# Run from the repository root regardless of the caller's cwd.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# Preflight: both toolchains must be installed before we spawn anything.
if [[ ! -x .venv/bin/python ]]; then
  echo "error: .venv not found — run 'make install' first." >&2
  exit 1
fi
if [[ ! -d frontend/node_modules ]]; then
  echo "error: frontend/node_modules not found — run 'make install' first." >&2
  exit 1
fi

# Process substitution (not a pipeline) keeps $! pointing at the real server
# process so the trap below can kill it; sed -u keeps log lines unbuffered so
# both streams interleave live.
.venv/bin/python -m uvicorn backend.api.main:app --reload \
  --host "$HOST" --port "$PORT" \
  > >(sed -u 's/^/[backend]  /') 2>&1 &
backend_pid=$!

(cd frontend && npm run dev) > >(sed -u 's/^/[frontend] /') 2>&1 &
frontend_pid=$!

echo "[run_dev] backend  pid=$backend_pid  http://localhost:$PORT"
echo "[run_dev] frontend pid=$frontend_pid  http://localhost:3000"
echo "[run_dev] press Ctrl-C to stop both"

cleanup() {
  # Disarm the traps so the kill below cannot re-enter this handler.
  trap - INT TERM EXIT
  # Negative PIDs address the process groups created by `set -m`, taking the
  # full npm/next and uvicorn/reloader trees down together.
  kill -TERM -- -"$backend_pid" -"$frontend_pid" 2>/dev/null || true
  # Reap children; ignore their (expected) non-zero termination statuses.
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# Wait for whichever process exits first; `|| status=$?` keeps set -e from
# aborting before we can propagate the real exit code.
status=0
wait -n || status=$?
cleanup
exit "$status"
