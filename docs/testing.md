# Testing & Local Development

This guide explains how to install, test, lint, and build AutoDev Architect
locally. Every command below is wrapped by the root [`Makefile`](../Makefile),
so the fastest path is `make <target>`. The equivalent raw commands are listed
too, in case you prefer to run them by hand.

> **Clean-tree guarantee.** Running `make install`, `make test`, or `make build`
> never dirties your git working tree. Every artifact these targets create
> (the `.venv`, `__pycache__`, `node_modules`, `.next`, `tsconfig.tsbuildinfo`,
> pytest/coverage caches, …) is listed in [`.gitignore`](../.gitignore).
> After a full cycle, `git status` should still report a clean tree. If you ever
> want a pristine checkout, `make clean` removes all generated files.

---

## Prerequisites

| Tool       | Version            | Used for                          |
|------------|--------------------|-----------------------------------|
| Python     | 3.10+ (3.11 in CI) | backend API, CLI, pytest          |
| Node.js    | 20+ (22 supported) | Next.js frontend, vitest          |
| npm        | bundled with Node  | frontend dependency management    |
| Docker     | optional           | full-stack `make docker-up`       |

Check what you have:

```bash
python3 --version
node --version
npm --version
```

---

## 1. Install

```bash
make install
```

This creates the Python virtualenv at `.venv`, installs backend runtime + test
dependencies from `backend/requirements.txt`, and installs the frontend node
modules. You do **not** need to activate the virtualenv yourself — every `make`
target calls `.venv/bin/python` directly.

Granular targets:

```bash
make install-backend    # .venv + backend/requirements.txt only
make install-frontend   # frontend/ node modules only
make install-dev        # optional dev tools: black, ruff, mypy, pytest-cov
```

> `black`, `ruff`, `mypy`, and `pytest-cov` are **not** part of the default
> install (to keep the runtime footprint small). Run `make install-dev` before
> using `make lint`, `make format`, `make typecheck`, or `make coverage`.

Raw equivalents:

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install
```

---

## 2. Run the tests

Run everything (backend + frontend):

```bash
make test
```

### Backend tests (pytest)

```bash
make test-backend
# raw:
.venv/bin/python -m pytest tests backend/tests -q
```

The suite spans **205+ tests** across two locations:

- `tests/backend/` — API, CLI, orchestrator, LLM factory, config.
- `backend/tests/` — agents, plans, patches, validation, skills, repository
  intelligence, observability, job queue, sandbox runner, tree-sitter provider.

`tests/conftest.py` puts the repository root on `sys.path`, and
`backend/pyproject.toml` sets `pythonpath = ["."]`, so the suites run from a
plain source checkout — no editable install required.

Useful pytest invocations (after `source .venv/bin/activate`, or prefix with
`.venv/bin/python -m`):

```bash
pytest tests backend/tests -q              # quiet, full run
pytest backend/tests/test_patch_engine.py  # a single file
pytest -k "orchestrator" -q                # filter by keyword
pytest -x -q                               # stop at first failure
pytest -vv                                 # verbose, show each test
```

### Frontend tests (vitest)

```bash
make test-frontend
# raw:
cd frontend && npm test
```

Vitest picks up `frontend/lib/**/*.test.ts` (see `frontend/vitest.config.ts`).

---

## 3. Coverage (optional)

Requires `make install-dev` (for `pytest-cov`):

```bash
make coverage
```

Prints a `term-missing` report and writes an HTML report to `htmlcov/`
(git-ignored). Open `htmlcov/index.html` in a browser to drill in.

---

## 4. Lint, format, typecheck (optional)

Requires `make install-dev` for the backend Python tools:

```bash
make lint         # ruff (backend) + eslint (frontend)
make format       # black + ruff --fix (backend)
make typecheck    # mypy (backend) + tsc --noEmit (frontend)
```

The frontend tools (`eslint`, `tsc`) ship with `make install-frontend`, so
`make lint-frontend` and `make typecheck-frontend` work without `install-dev`.

---

## 5. Build

```bash
make build          # production build of the Next.js frontend
make build-frontend # same thing, explicit
```

The backend is a FastAPI app served from source (no compile step); run it with
`make run-backend`.

---

## 6. Run the servers

```bash
make run-backend    # FastAPI on http://localhost:8000 (autoreload)
make run-frontend   # Next.js dev server on http://localhost:3000
```

Override host/port: `make run-backend PORT=9000 HOST=127.0.0.1`.

Configure the LLM provider via `.env` (copy from `.env.example`) before
starting the backend — see the [README](../README.md) for provider options
(`stub`, `openai`, `ollama`).

Full stack via Docker:

```bash
make docker-up      # build + boot backend (:8000) and frontend (:3000)
make docker-down    # tear it down
```

---

## 7. Reproduce CI locally

The GitHub Actions pipelines run the backend pytest suite
(`.github/workflows/ci-backend.yml`) and the frontend lint → typecheck → test →
build sequence (`.github/workflows/ci-frontend.yml`). Reproduce both with:

```bash
make check          # lint + typecheck + tests + build, backend & frontend
make check-backend  # backend slice only
make check-frontend # frontend slice only
```

> `make check` uses the backend dev tools, so run `make install-dev` first.
> To mirror CI's backend job exactly (tests only, no lint/typecheck), run
> `make test-backend`.

---

## 8. Clean up

```bash
make clean       # remove build/test artifacts (tree returns to git-clean)
make distclean   # clean + delete .venv and frontend/node_modules
```

`make clean` removes `__pycache__`, `*.pyc`, pytest/ruff/mypy caches, coverage
output, `dist/`/`build/`/`*.egg-info`, the frontend `.next/`/`out/`/
`tsconfig.tsbuildinfo`, and generated files under `tests/reports/` (keeping the
`.gitkeep`). None of these are tracked by git, so cleaning is always safe.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `make: python3: command not found` | Install Python 3.10+, or `make install PYTHON=python3.11`. |
| `ruff/black/mypy: No module named ...` | Run `make install-dev`. |
| `ModuleNotFoundError: backend` in pytest | Run from the repo root; `tests/conftest.py` adds it to `sys.path`. |
| Occasional `test_sandbox_runner.py` failures in a full run | Known low-frequency flake — those tests spawn real subprocesses and can be timing-sensitive under load. They pass in isolation (`pytest backend/tests/test_sandbox_runner.py`); re-running `make test-backend` clears it. |
| Frontend `next: not found` | Run `make install-frontend`. |
| `git status` shows generated files | Open an issue — every artifact should be in [`.gitignore`](../.gitignore); `make clean` is the stopgap. |
