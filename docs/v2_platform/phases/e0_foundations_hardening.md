# E0 — Foundations & Hardening

**Wave:** Alpha (complete within Alpha; everything else depends on it)
**Status:** In progress · **Stories:** 1/7 complete
**Depends on:** — (root of the dependency graph)
**Enables:** E1, E2 (transitively E3-E13); direct consumers: E1-S1/S2/S3 (E0-S1), E3-S2 (E0-S2), E11-S1 (E0-S3), E1-S3 (E0-S4)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.6 (E0), §18.8, §18.9

## Objective

Establish the security, configuration, and observability baseline, and make
**PostgreSQL** the default persistence backend (while keeping SQLite for the
local-first mode).

## Key result

A platform skeleton that boots locally (SQLite + stub provider) and in production
(PostgreSQL + Redis + MinIO) with no code change, already emitting traces/metrics via
OpenTelemetry and with validated declarative configuration.

## Stories

### E0-S0 — Containerized developer/test runtime

Subtasks:
- `E0-S0-T1`: backend dev/test container with an in-container `.venv`.
- `E0-S0-T2`: Compose wiring for backend tests, CLI, and local SQLite/config state.
- `E0-S0-T3`: README and v2 usage instructions for container startup and command execution.

| Criterion | Detail |
| --- | --- |
| Functional | Backend tests and CLI commands run inside the backend container; host `.venv` is not required for E0 execution; local profile state is isolated in Docker volumes |
| Non-functional | Local-first container boot remains on the stub provider and SQLite; no paid service or external cloud dependency is required |
| DoR (specific) | Existing Dockerfile/Compose and host Makefile behavior inventoried |
| DoD (specific) | README documents startup; v2 docs identify container execution as the E0 baseline |
| Dependencies | — (root of the epic) |

### E0-S1 — Container-first Makefile workflow

Subtasks:
- `E0-S1-T1`: canonical Makefile targets for container build/up/shell/test/check/down/logs.
- `E0-S1-T2`: docs point E0 agents and contributors to container targets first.
- `E0-S1-T3`: local convenience targets remain available but are no longer the E0 validation path.

| Criterion | Detail |
| --- | --- |
| Functional | A contributor can build, enter, test, check, inspect logs, and stop the E0 backend container through Makefile targets |
| Non-functional | Targets are deterministic wrappers around Docker Compose and do not create tracked artifacts |
| DoR (specific) | E0-S0 container runtime available |
| DoD (specific) | Makefile help exposes the container targets; docs/testing.md documents the workflow |
| Dependencies | E0-S0 |

### E0-S2 — Declarative, typed configuration layer

Subtasks:
- `E0-S2-T1`: config schema (Pydantic Settings) with local/prod profiles.
- `E0-S2-T2`: loading from env/file with precedence.
- `E0-S2-T3`: fail-fast validation + `config validate` command.

| Criterion | Detail |
| --- | --- |
| Functional | Invalid config aborts boot with an actionable message; `local` (SQLite/stub) and `prod` (PostgreSQL/Redis/MinIO) profiles selectable via variable; secrets never logged |
| Non-functional | Boot with valid config < 2 s; 100% of fields typed with a safe default; module coverage >= 85% |
| DoR (specific) | Inventory of all current v1 variables completed |
| DoD (specific) | `docs/config.md` published; local x prod matrix tested in CI |
| Dependencies | E0-S1 |

### E0-S3 — Migration to PostgreSQL as the default State Store

Subtasks:
- `E0-S3-T1`: initial modeling (sessions/runs/steps) with Alembic.
- `E0-S3-T2`: repository abstraction agnostic to SQLite/PostgreSQL.
- `E0-S3-T3`: reversible migration/seed.

| Criterion | Detail |
| --- | --- |
| Functional | Same test suite passes on SQLite and PostgreSQL; migrations apply and roll back; dev seeds available |
| Non-functional | Migration versioned and reversible; RPO <= 5 min / RTO <= 30 min documented; no downtime on additive migrations |
| DoR (specific) | ADR "PostgreSQL as default" approved |
| DoD (specific) | Backup/restore runbook in `docs/ops/`; migration round-trip test in CI |
| Dependencies | E0-S2 |

### E0-S4 — Observability baseline (OpenTelemetry)

Subtasks:
- `E0-S4-T1`: request/step tracing.
- `E0-S4-T2`: metrics (counters/histograms) and OTLP exporter.
- `E0-S4-T3`: trace <-> run <-> step correlation.

| Criterion | Detail |
| --- | --- |
| Functional | Every request and every step produce a span correlated to `run_id`/`step_id`; latency and error metrics exposed |
| Non-functional | Tracing overhead < 5% of latency; configurable sampling; no PII in spans |
| DoR (specific) | Span/metric naming convention defined |
| DoD (specific) | Base dashboard published; error-rate alert active in staging |
| Dependencies | E0-S2 |

### E0-S5 — Security baseline and secrets hygiene

Subtasks:
- `E0-S5-T1`: secret management (env/secret store) with no hardcoding.
- `E0-S5-T2`: secret scanning and SCA in CI.
- `E0-S5-T3`: default HTTP security headers.

| Criterion | Detail |
| --- | --- |
| Functional | No secret in the repository; pipeline blocks a PR with a secret/critical CVE |
| Non-functional | Sandbox defaults to no network; no critical-CVE dependencies; scanning < 3 min in CI |
| DoR (specific) | CVE severity policy agreed |
| DoD (specific) | `run_secret_scanning` integrated; `docs/security/baseline.md` |
| Dependencies | E0-S2 |

### E0-S6 — Redis (Cache/Queue/Locks) and MinIO (Artifact Store)

Subtasks:
- `E0-S6-T1`: Redis connection with distributed locks.
- `E0-S6-T2`: MinIO/S3 client for artifacts.
- `E0-S6-T3`: local fallback without these dependencies.

| Criterion | Detail |
| --- | --- |
| Functional | Distributed locks prevent duplicate execution; artifacts (patch/log) persist and are recoverable; local mode degrades without crashing |
| Non-functional | Lock with timeout/renewal; artifact put/get p95 < 200 ms locally; coverage >= 85% |
| DoR (specific) | Key/bucket naming convention defined |
| DoD (specific) | Lock-contention test; `docs/ops/storage.md` |
| Dependencies | E0-S2 |

## v1 precursor / starting point

- SQLite persistence + a `Store`/repository abstraction and a versioned migration
  runner already exist and are `default` (`backend/persistence/`, see
  `docs/feature_matrix.md` § Persistence) — this is the closest existing analogue to
  E0-S2's SQLite side; the PostgreSQL adapter (`backend/persistence/postgres_adapter.py`)
  is currently a `stub` that raises `NotImplementedError`.
- Request-ID tracing middleware and a Prometheus `GET /metrics` endpoint are `default`;
  OpenTelemetry is `optional` (only active if the package is importable) — E0-S3
  should make it a first-class, always-on dependency rather than best-effort.
- `RedisJobQueue` (`backend/jobs/queue.py`) is a `stub`; MinIO integration is
  `planned`. CORS is currently hardcoded to `localhost:3000` and env-driven CORS is
  still `planned` (`mvp_refactor_plan.md` Unit 5) — folds into E0-S4.
- A centralized typed settings module (`pydantic-settings`) and a `GET /features`
  feature-flag endpoint are `planned` (`mvp_refactor_plan.md` Unit 4) — this is
  exactly E0-S2 after the container and Makefile execution baseline.

## Story status

| Story | Status | Evidence |
| --- | --- | --- |
| E0-S0 | Done | Containerized backend dev/test runtime, Compose wiring, README startup instructions |
| E0-S1 | Not started | — |
| E0-S2 | Not started | — |
| E0-S3 | Not started | — |
| E0-S4 | Not started | — |
| E0-S5 | Not started | — |
| E0-S6 | Not started | — |

## Epic exit checklist

- [ ] All 7 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Contract tests green for the config/observability surfaces this epic introduces.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Alpha wave exit criteria this epic contributes to (§18.9) satisfied.
