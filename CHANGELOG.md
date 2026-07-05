# Changelog

All notable changes to AutoDev Architect are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); dates are `YYYY-MM-DD`.

## [Unreleased] — v2.0 Alpha (in progress)

The v2.0 platform rewrite is underway on `main`. Per-story detail lives in
[`docs/v2_platform/progress.md`](docs/v2_platform/progress.md) (Changelog section);
epic summaries:

### E0 — Foundations & Hardening (complete, 2026-07-04, PRs #51–#52)

- Containerized backend dev/test runtime with Makefile `container-*` targets.
- Typed declarative settings with local/prod profiles, JSON+env precedence, and a
  fail-fast `autodev config validate` CLI (`docs/config.md`).
- PostgreSQL-backed sessions/runs/messages/plans selected via `DATABASE_URL`
  (ADR-001), with a backup/restore runbook (`docs/ops/backup_restore.md`).
- OpenTelemetry request and run-step spans, Prometheus 5xx counters
  (`docs/ops/observability.md`).
- Default HTTP security headers, opt-in HSTS, dependency-free secret scanning, and a
  backend CI secret/SCA gate (`docs/security/baseline.md`).
- Redis queue/cache/locks and local/MinIO artifact stores wired into the
  production-like Compose profile (`docs/ops/storage.md`).

### E1 — Plugin Core & SDK (complete, 2026-07-04, PR #53)

- `plugin.yaml` manifest schema, typed extension-point catalog, published JSON schema
  (RFC-001, ADR-002, `docs/plugins/manifest.md`).
- Plugin Host discovery (directories + entry points) with durable
  install/enable/disable/uninstall lifecycle and `hostApi` compatibility rejection.
- Default-deny fs/net/exec/secrets permission model with brokered Host API access and
  `plugin.permission.denied` audit events (`docs/plugins/permissions.md`).
- SemVer-versioned Python SDK, `sdk new plugin` scaffolding, contract-test harness,
  runnable example plugin (`docs/sdk/write-your-first-plugin.md`).
- Active-plugin registry with `GET /v2/plugins/active` (`docs/plugins/registry.md`).

### E2 — Agent Framework (complete, 2026-07-04, PR #54)

- Versioned `agent.yaml` manifest validator with strict typed IO and safe default
  budgets (ADR-003, `docs/agents/manifest.md`).
- Durable Agent Registry with SemVer resolution, capability search, deprecation
  signaling, and `GET /v2/agents/catalog` (`docs/agents/registry.md`).
- Agent Runtime with fail-closed token/cost/step/tool-call budgets, output
  guardrails, per-step traces, and token/cost metrics (`docs/agents/runtime.md`).
- Permissioned tool/skill mediation, default network denial, provider protocol with
  an offline stub LLM provider, and per-run/tenant metering.
- `autodev/agent-coder` packaged as an installable reference agent plugin with v1
  behavior-parity coverage.

### Governance (2026-07-04)

- Apache-2.0 `LICENSE`, `NOTICE` attribution, and `CITATION.cff` added; backend
  package metadata aligned from MIT to Apache-2.0 (closes the "no LICENSE file"
  limitation flagged in the v1 release).
- `CONTRIBUTING.md`: epic/story branching model, docstring/type-hint standards, and
  story-scoped vs full-suite testing policy; PR and issue templates under `.github/`.
- Optional parallel test execution via `make test-backend-parallel` (pytest-xdist).

## [v1] — 2026-07-02 — v1 architecture baseline (pre-v2 rewrite)

Published as the [autodev v1 release](https://github.com/acpguedes/autodev/releases/tag/v1) (tag `v1`).

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
Start at [`docs/v2_platform/progress.md`](docs/v2_platform/progress.md) for current status.
E0–E2 have since completed (see the Unreleased section above); the next epic is
**E3 — Orchestration Engine** (see
[`docs/v2_platform/phases/e3_orchestration_engine.md`](docs/v2_platform/phases/e3_orchestration_engine.md)
and [`docs/v2_platform/agent_guide.md`](docs/v2_platform/agent_guide.md) before starting).
