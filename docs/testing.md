# Testing & Local Development

This guide explains how to install, test, lint, and build AutoDev Architect.
E0 v2 platform work uses the backend container as the canonical execution
environment. Every command below is wrapped by the root
[`Makefile`](../Makefile), so the fastest path is `make <target>`.

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
| Docker     | required for E0    | container-first backend workflow  |

Check what you have:

```bash
python3 --version
node --version
npm --version
```

---

## 1. Container-first backend workflow

Use these targets for E0 backend development, tests, CLI commands, migrations,
and validation:

```bash
make container-build   # build the backend dev/test image
make container-up      # boot FastAPI on http://localhost:8000
make container-test    # pytest + backend coverage gate inside the container
make container-check   # ruff + mypy + pytest inside the container
make container-shell   # interactive shell with the in-container .venv active on PATH
make container-logs    # follow backend logs
make container-down    # tear down the Compose stack
```

The backend image owns `/workspace/.venv`; do not rely on the host `.venv` for
E0 validation. Source directories are bind-mounted into `/workspace`, and
SQLite/config state is stored in Docker volumes.

Raw equivalents:

```bash
docker compose -f infrastructure/docker-compose.yml build backend
docker compose -f infrastructure/docker-compose.yml run --rm backend pytest tests backend/tests -q
docker compose -f infrastructure/docker-compose.yml run --rm backend python -m backend.cli config show
```

## 2. Host install

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

## 3. Run the tests

Run everything (backend + frontend):

```bash
make test
```

### Test pyramid & layout

AutoDev's backend suite is organized as three tiers, bottom to top:

| Tier | Location | What it covers | External I/O |
|------|----------|-----------------|---------------|
| Unit | `backend/tests/unit/<subsystem>/` | A single module/class in isolation | None — no network, no live services, no real LLM/API/Docker calls |
| Integration | `backend/tests/integration/` | Real in-process component boundaries (SQLite persistence, FastAPI `TestClient`, plugin host, orchestrator wiring) | In-process only — no outbound network, no external API keys |
| E2E | `frontend/e2e/*.spec.ts` (Playwright) + the `smoke-e2e` CI job | The real FastAPI backend and the built Next.js app driven together through a browser | Real local processes (backend on `:8000`, frontend dev server); frontend specs intercept `/v2/*` requests so they stay deterministic even when a live backend isn't reachable |

`<subsystem>` mirrors the `backend/` package layout (e.g.
`backend/tests/unit/agents/`, `backend/tests/unit/patches/`), so a test's path
tells you which product module it protects. `backend/tests/fixtures/` holds
shared deterministic fixtures usable from either the unit or integration
tier. Top-level `tests/` (repo root) keeps the pre-existing API/CLI/
orchestrator/config suite and is unaffected by this layout.

Pytest markers (registered in `backend/pyproject.toml`) let you select a tier
without relying on paths:

```bash
pytest -m unit -q
pytest -m integration -q
```

**Determinism / stub-provider policy — mandatory for the unit tier:**

- No network calls, no live external services, no real LLM provider, no real
  git remotes, no real Docker/sandbox execution. Use `StubLLMProvider`
  (`backend/agents/provider.py`) and the fixtures under
  `backend/tests/fixtures/` for anything that would otherwise reach outside
  the process.
- The integration tier may exercise real in-process components (SQLite,
  `TestClient`) but still must not require outbound network access or real
  credentials — CI runs with no external services configured.
- The e2e tier boots real backend/frontend processes but keeps browser specs
  deterministic by mocking `/v2/*` API responses at the network layer (see
  the existing specs under `frontend/e2e/`).

A flaky or non-deterministic test blocks the tier it belongs to — fix or stub
the dependency rather than adding retries.

### Contract tests

`backend/tests/contract/` is a dedicated tier (E12-S2) that pins the
**extension-point contracts** plugins are built against: for each
[`ExtensionPointKind`](../backend/plugins/catalog.py) declared in
`backend/plugins/catalog.py`, a contract test asserts that its Protocol/ABC
shape has not silently changed, and — where the extension point has a
manifest format — that the validator round-trips a minimal valid document
and rejects an invalid one. It has no separate Makefile/CI entry: it is
plain `backend/tests/` content, so `make test-backend` / CI collect and
gate it exactly like the unit and integration tiers, including the 85%
coverage requirement from §4 below.

| Extension point | Contract test module | What it guarantees |
|---|---|---|
| `agent` | `backend/tests/contract/test_agent_contract.py` | `Agent` structural Protocol shape (`backend/agents/base.py`) is stable; `agent.yaml` round-trips via `validate_agent_manifest()` |
| `skill` | `backend/tests/contract/test_skill_contract.py` | `Skill`/`BaseSkill` shape (`backend/skills/base.py`) is stable; `skill.yaml` round-trips via `validate_manifest()` |
| `reasoning` | `backend/tests/unit/reasoning/test_reasoning_contract.py` | Reused as-is from E4-S1 — not duplicated |
| `router`, `selector` | `backend/tests/unit/routing/test_routing_contract.py` | Reused as-is from E5-S1/S2 — not duplicated (selector is validated as part of the same `RoutingPolicy`) |
| `evaluator` | `backend/tests/unit/evals/test_evals_contract.py` | Reused as-is — not duplicated |
| `context_provider` | `backend/tests/contract/test_context_provider_contract.py` | `ContextProvider` runtime-checkable Protocol shape (`backend/context/provider.py`) is stable, verified against a real implementation |
| `tool`, `retriever`, `validation_gate`, `ui_panel`, `event_handler` | *(pending — see below)* | Declared in the catalog but have no dedicated Protocol/manifest of their own yet |
| LLM provider *(cross-cutting, not a catalog kind)* | `backend/tests/contract/test_provider_contract.py` | `LLMProvider` structural Protocol shape (`backend/agents/provider.py`) is stable |
| Flow *(cross-cutting, not a catalog kind)* | `backend/tests/contract/test_flow_contract.py` | `flow.yaml` round-trips via `validate_flow_manifest()` |
| `hostApi` SemVer compatibility | `backend/tests/contract/test_host_api_compatibility.py` | `PluginHost` rejects an incompatible declared range and installs a compatible one; every published `*_CONTRACT_HOST_API` is satisfied by `HOST_API_VERSION` |

**Mandatory build gate.** `backend/tests/contract/test_extension_point_coverage.py`
is parametrized over every member of `ExtensionPointKind` and asserts each
one is registered in `backend/tests/contract/_harness.py`'s coverage map —
either `COVERED` (with an importable contract test module) or `PENDING`
(with a written rationale for why no Protocol/manifest exists yet). Adding a
new extension-point kind to the catalog without registering it there fails
the build immediately, rather than silently shipping an uncontracted
extension point.

**Marketplace prerequisite.** A green contract suite is the mandatory
prerequisite for publishing a plugin to the Marketplace (E13): the
Marketplace consumer itself is out of scope for E12-S2 and is not built
here, but any future publish path must require
`backend/tests/contract` to pass (and, per the coverage gate above, every
extension point the plugin declares to be registered with a real contract)
before accepting a submission.

### Backend tests (pytest)

```bash
make test-backend
# raw:
.venv/bin/python -m pytest tests backend/tests -q
```

The suite spans **285+ tests** across two locations:

- `tests/backend/` — API, CLI, orchestrator, LLM factory, config.
- `backend/tests/` — agents, plans, patches, validation, skills, repository
  intelligence, observability, job queue, sandbox runner, tree-sitter
  provider, organized into `unit/<subsystem>/` and `integration/` per the
  layout above.

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

### Story-scoped test runs (v2 workflow policy)

Per `CONTRIBUTING.md` §4, story branches run **only the tests covering the
story's code** — plus dependent areas when the story touches a shared contract
(manifest schemas, persistence, the plugin host). Examples:

```bash
pytest backend/tests/agents -q            # story touched the agent framework
pytest backend/tests -k "registry" -q     # selection by keyword
```

The **full suite** (`make check` / `make container-check`) is mandatory only at
the epic → `main` PR gate. Do not add tests that duplicate existing coverage —
every new test must protect a behavior delivered by the story.

### Parallel execution (pytest-xdist)

The backend suite is parallel-safe. Measured on this repository
(2026-07-04, `pytest -n auto`): **285/285 tests pass, wall time drops from
~1m52s (serial) to ~57s (parallel)**.

```bash
make install-dev                          # installs pytest-xdist
.venv/bin/python -m pytest tests backend/tests -q -n auto
# or:
make test-backend-parallel
```

Caveats:

- The serial result is authoritative: if a test fails only under `-n auto`
  (most likely the timing-sensitive `test_sandbox_runner.py` cases — see
  Troubleshooting), re-run serially before treating it as a real failure.
- The coverage gate (`--cov`) also works under xdist, but keep CI on the
  serial path until parallel runs have been flake-free for a while.

### Frontend tests (vitest)

```bash
make test-frontend
# raw:
cd frontend && npm test
```

Vitest picks up `frontend/lib/**/*.test.ts` (see `frontend/vitest.config.ts`).

---

## 4. Coverage

`make test-backend` (and CI's `backend-tests` job) enforce a **coverage gate
of 85% on product code**: `--cov=backend --cov-fail-under=85`, with
`backend/tests/*` omitted via the root `.coveragerc`. pytest-cov auto-discovers
this file when pytest runs from the repo root, which is how every
`make test-backend*` / CI invocation runs. The omit matters — without it,
coverage.py counts the test files themselves as "covered by being executed",
which inflates the number and hides real gaps in `backend/` (raw/unfiltered
coverage on this repo is ~93%; the product-code-only figure the gate enforces
is ~88%).

The `.coveragerc` repeats the same `omit = backend/tests/*` pattern under
**both** `[run]` and `[report]`. `[run] omit` alone is not enough: it
controls what coverage.py measures during collection, but does not
reliably keep already-imported test modules out of the generated
term/XML/HTML reports. `[report] omit` is what actually filters those
reports (the `[xml]` section has no `omit` of its own — it inherits
`[report]`'s), so both sections are required for the gate to measure
product-only coverage correctly.

```bash
make test-backend
# raw:
.venv/bin/python -m pytest tests backend/tests -q \
  --cov=backend --cov-report=term-missing --cov-report=xml:coverage.xml \
  --cov-fail-under=85
# (backend/tests/* is omitted via the root .coveragerc, picked up automatically)
```

This also writes `coverage.xml` (Cobertura format), which CI uploads as a
build artifact and summarizes in the job's step summary
(`scripts/ci_coverage_summary.py`).

For an HTML report to drill into locally (requires `make install-dev` for
`pytest-cov`):

```bash
make coverage
```

Writes `htmlcov/` (git-ignored) — open `htmlcov/index.html` in a browser.

---

## 5. Lint, format, typecheck (optional)

Requires `make install-dev` for the backend Python tools:

```bash
make lint         # ruff (backend) + eslint (frontend)
make format       # black + ruff --fix (backend)
make typecheck    # mypy (backend) + tsc --noEmit (frontend)
```

The frontend tools (`eslint`, `tsc`) ship with `make install-frontend`, so
`make lint-frontend` and `make typecheck-frontend` work without `install-dev`.

---

## 6. Build

```bash
make build          # production build of the Next.js frontend
make build-frontend # same thing, explicit
```

The backend is a FastAPI app served from source (no compile step); run it with
`make run-backend`.

---

## 7. Run the servers

```bash
make run-backend    # FastAPI on http://localhost:8000 (autoreload)
make run-frontend   # Next.js dev server on http://localhost:3000
```

Override host/port: `make run-backend PORT=9000 HOST=127.0.0.1`.

Configure the LLM provider via `.env` (copy from `.env.example`) before
starting the backend — see the [README](../README.md) for provider options
(`stub`, `openai`, `ollama`).

Backend stack via Docker:

```bash
make container-up      # build + boot backend (:8000)
make container-down    # tear it down
```

---

## 8. Reproduce CI locally

Three GitHub Actions workflows gate every PR:

- `.github/workflows/ci-backend.yml` — secret/CVE scan, then the backend
  pytest suite with the 85% coverage gate.
- `.github/workflows/ci-frontend.yml` — frontend lint → typecheck → unit
  test → build.
- `.github/workflows/ci-e2e.yml` — smoke e2e: boots the backend
  (`uvicorn backend.api.main:app`), health-probes `/docs`, then runs the
  Playwright suite (`frontend/e2e/`) against the built Next.js app.

Reproduce the first two with:

```bash
make check          # lint + typecheck + tests + build, backend & frontend
make check-backend  # backend slice only
make check-frontend # frontend slice only
```

> `make check` uses the backend dev tools, so run `make install-dev` first.
> To mirror CI's backend job exactly (tests only, no lint/typecheck), run
> `make test-backend`.

Reproduce the e2e smoke job:

```bash
.venv/bin/python -m uvicorn backend.api.main:app --port 8000 &
curl -sf --retry 10 --retry-delay 2 --retry-connrefused http://localhost:8000/docs
cd frontend && npx playwright install --with-deps chromium && npm run e2e
```

Playwright's `webServer` config (`frontend/playwright.config.ts`) starts the
Next.js dev server for you; override the port with `PLAYWRIGHT_PORT` if you
already have something listening on `:3000` (e.g. a sibling worktree).

> **Caveat when overriding `PLAYWRIGHT_PORT`:** `frontend/lib/api.ts`'s
> `getDefaultApiBaseUrl()` only defaults the API base to `http://localhost:8000`
> when the frontend itself is served from `localhost:3000` exactly; on any
> other port it falls back to same-origin requests. The `sessions-config.spec.ts`
> mocks intercept the hardcoded `http://localhost:8000/v2/**` origin, so
> running the frontend on a non-3000 port (and/or the backend on a non-8000
> port) makes those specs fail with "endpoint unavailable" — not a real
> regression, just a mismatch between the port override and this hardcoded
> default. Use the default ports (`:3000` frontend / `:8000` backend) to
> reproduce the e2e job faithfully; CI's `ci-e2e.yml` always does.

---

## 9. Clean up

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
