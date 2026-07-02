# Changelog

All notable changes to AutoDev Architect are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); dates are `YYYY-MM-DD`.

## [v1.0.0] — 2026-07-02 — v1 architecture baseline (pre-v2 rewrite)

This tag freezes the current **v1 linear-pipeline architecture** as a stable, versioned
checkpoint immediately before the **v2.0 platform rewrite** begins (plugin core, agent
framework, flow engine, and the rest of the E0–E13 roadmap — see
[`docs/architecture/v2_platform_reference.md`](docs/architecture/v2_platform_reference.md) and
[`docs/v2_platform/`](docs/v2_platform/README.md)). It is not a new feature release; it is the
baseline the v2 epics are built on top of and measured against.

Package versions (`backend/pyproject.toml`, `frontend/package.json`) stay at `0.1.0` — this tag
numbers the **architecture generation** ("v1" vs. "v2"), the same terminology already used
throughout `docs/v2_platform/`, not a semver maturity claim about the packages themselves. The
project remains pre-production/MVP-stage; see "Known limitations" below.

### What ships in this baseline

Full, precise `default` / `optional` / `stub` / `planned` status for every feature lives in
[`docs/feature_matrix.md`](docs/feature_matrix.md) (refreshed as part of this release — see
"Docs" below). Summary of what's `default` or `optional` today:

- **Backend control plane** — FastAPI app; SQLite persistence via a Repository/Store
  abstraction with versioned migrations; stub/OpenAI/Ollama LLM providers (LRU-cached); the
  linear 7-agent pipeline (Navigator → Analyzer → Architect → Coder → DevOps → Validator →
  Responder) plus specialized `security`/`refactor`/`docs` agents; dynamic multi-agent
  orchestration behind `AUTODEV_DYNAMIC_ORCH`; a skills registry with deterministic built-ins;
  a plan store with an approve/reject API; patch generation (unified diff) with dry-run-by-
  default apply; a flag-gated, hardened Docker/subprocess validation sandbox that fails closed
  without Docker; an in-process async job queue; request-ID tracing + Prometheus `/metrics`.
- **Settings & security** — a centralized `pydantic-settings` module and `GET /features`
  (partial — see the matrix for what's not yet migrated off scattered env reads); opt-in
  bearer-token API auth (`AUTODEV_API_TOKEN`); LLM API key redaction in `/config`/`/features`
  responses; `0600` permissions on `autodev.config.json`; env-driven CORS
  (`AUTODEV_CORS_ORIGINS`); filesystem path confinement on `/repository/symbols`. Full threat
  model in [`docs/security.md`](docs/security.md).
- **Frontend** — Next.js 14 App Router, six pages (chat, config, agents, plans, skills,
  patches); a Tailwind + shadcn/ui foundation landed (design tokens, `ThemeProvider`, one
  `Button` primitive) but is not yet adopted by any page or component.
- **Infrastructure & CI** — Docker Compose (backend + frontend, `LLM_PROVIDER=stub` by
  default); backend CI with a coverage gate (`--cov-fail-under=60`) and a boot smoke test
  hitting `/health`; frontend CI running lint, typecheck, unit tests, and a production build.
- **Tests** — 213 backend tests at 93% coverage; 3 frontend unit tests; both suites green via
  `make check`.

### Known limitations

Not exhaustive — see [`docs/feature_matrix.md`](docs/feature_matrix.md),
[`docs/architecture/weaknesses_and_strategies.md`](docs/architecture/weaknesses_and_strategies.md),
and [`docs/security.md`](docs/security.md) ("Known residual risks") for the full, honest
breakdown. Highlights relevant to anyone picking up this baseline:

- PostgreSQL, the Redis job queue, MinIO artifact storage, and pgvector are all
  stubs/`NotImplementedError` or not yet wired — SQLite + the in-process queue is the only
  durable path today.
- tree-sitter symbol extraction is a **stub**: it always delegates to the lexical/regex
  provider, with or without the `tree_sitter` package installed.
- Plan approval does not gate execution — `execute_plan()` is a mock that stamps tasks as
  completed without running real actions, regardless of plan status.
- **No `LICENSE` file exists at the repository root**, even though `backend/pyproject.toml`
  declares `license = { text = "MIT" }`. Worth adding explicitly before wider distribution of
  this tag — flagged here rather than added unilaterally since the copyright holder line is a
  decision for the maintainer.
- No dependency lockfile (`requirements.txt` / `pyproject.toml` use unbounded `>=`
  constraints); container base images use mutable tags (`python:3.11-slim`, `node:20`).

### Validated before tagging

- `make check` — ruff, mypy, the full pytest suite with the coverage gate, and frontend
  lint/typecheck/vitest/build — all green.
- `docker compose -f infrastructure/docker-compose.yml config` — valid.
- Fixed two pre-existing mypy failures in `backend/tests/test_api_security.py` (untyped
  generator fixture, unannotated mixed-value dict) uncovered while validating this baseline.

### Docs

- Refreshed [`docs/feature_matrix.md`](docs/feature_matrix.md): corrected several rows that had
  gone stale relative to already-merged work (typed settings module, `GET /features`, env-driven
  CORS, CI coverage/smoke-test gates, the Tailwind/shadcn foundation), added a new **Security**
  section, and reclassified tree-sitter extraction as a `stub`.
- Updated the status banner in
  [`docs/architecture/weaknesses_and_strategies.md`](docs/architecture/weaknesses_and_strategies.md)
  to match.

### What's next

The v2.0 platform rewrite is tracked under [`docs/v2_platform/`](docs/v2_platform/README.md).
Start at [`docs/v2_platform/progress.md`](docs/v2_platform/progress.md) for current status; the
next story to pick up is **E0-S1 — declarative, typed configuration layer** (see
[`docs/v2_platform/phases/e0_foundations_hardening.md`](docs/v2_platform/phases/e0_foundations_hardening.md)
and [`docs/v2_platform/agent_guide.md`](docs/v2_platform/agent_guide.md) before starting).
