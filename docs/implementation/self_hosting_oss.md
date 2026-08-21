# OSS Self-Hosting Guide

This guide documents the current self-hosting paths for AutoDev Architect using only open-source-friendly infrastructure.

---

## Goals of the current slice

- keep the default runtime operable without paid services;
- preserve state outside prompt text via local config and durable storage;
- support both UI-driven and CLI-driven operator workflows;
- offer a first-class local-model path through Ollama;
- ship a single, strategy-agnostic install path (the `autodev` CLI) that works the same on a laptop and in production.

---

## Supported operating modes

### 1. Deterministic bootstrap mode

Use this mode when you want a fully local setup without any live model dependency.

- `LLM_PROVIDER=stub`
- SQLite-backed durable store
- FastAPI backend
- Next.js frontend
- optional CLI via `python -m backend.cli` (or the installed `autodev` entry point, see below)

This is the safest initial path for contributors and CI-style smoke testing.

### 2. Local-model mode with Ollama

Use this mode when you want local inference without a hosted provider.

- `LLM_PROVIDER=ollama`
- `OPENAI_MODEL` or runtime config `llm.model` set to an Ollama-served model such as `llama3.1`
- `OLLAMA_BASE_URL` defaults to `http://localhost:11434/v1`
- the backend uses an OpenAI-compatible transport so the same typed runtime config works across providers

Recommended startup flow:

1. Start Ollama locally.
2. Pull the desired model in Ollama.
3. Save the provider/model settings through the web config workspace or the CLI.
4. Start the backend and frontend.

### 3. Hybrid hosted-provider mode

Use this when a hosted model is acceptable for some environments.

- `LLM_PROVIDER=openai`
- `OPENAI_API_KEY` required
- `OPENAI_BASE_URL` optional for compatible gateways/proxies

This mode should remain optional rather than required for core platform operation.

---

## Installing the `autodev` CLI (E34-S1)

`backend/pyproject.toml` declares a console-script entry point
(`autodev = "backend.cli:main"`) that `pip install -e backend/`, `pipx
install backend/`, and `uv tool install backend/` all resolve identically —
ADR-015 (Accepted) chose this pip-compatible package for the CLI, plus the
existing Compose bundle for the self-hosted platform, over a bespoke
installer. Full detail — `autodev --version`/`--shell`/`--command`, the
governed shell, and the clean-environment install verification script —
lives in [`docs/execution/cli-install.md`](../execution/cli-install.md).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e backend/
autodev --help
```

This install has no mandatory paid-service dependency: it defaults to
SQLite plus the stub LLM provider, the same local-first guarantee as the
deterministic bootstrap mode above.

### Self-host preflight and bootstrap (E34-S2)

- `autodev doctor` — read-only diagnostics covering settings/storage
  consistency, port availability, project-root writability, database
  reachability, and artifact storage backend. Exits non-zero if any check
  fails, so it is safe to run before deciding anything else.
- `autodev bootstrap` — runs the same preflight, then initializes the
  configured state store (SQLite or PostgreSQL) via the same idempotent
  migration runner every other entry point uses. Fails closed: a failing
  preflight check touches no state, and the command is safe to re-run.

Storage posture is explicit configuration, never a silent fallback:
`AUTODEV_PROFILE=local` requires a `sqlite://` `DATABASE_URL` plus local
artifact storage; `AUTODEV_PROFILE=prod` requires PostgreSQL plus
MinIO/S3 credentials. `autodev config validate --profile <local|prod>`
and `autodev doctor` both surface a mismatched posture before you run
anything against it.

### Upgrading (E34-S3)

`autodev upgrade [--backup-dir DIR] [--target-version X]` always backs up
the configured state and artifact stores first — reusing the same E8-S4
`BackupManager` tooling behind disaster recovery — and only then applies
any pending schema migrations. It refuses outright, rather than guessing,
if the database's recorded schema is newer than the installed code knows
about. Rollback is restore-from-the-pre-upgrade-backup, using the same
machinery as the
[E8 restore runbook](../v2_platform/runbooks/e8_restore_runbook.md). Full
detail: [`docs/execution/upgrade.md`](../execution/upgrade.md).

---

## Runtime configuration surfaces

The current repository exposes the same typed runtime state through:

- `GET /config` and `PUT /config`;
- the frontend config workspace;
- `python -m backend.cli config show`;
- `python -m backend.cli config set ...`.

This keeps configuration explicit, reviewable, and file-backed in `autodev.config.json`.

---

## Local startup checklist

### Backend

```bash
source .venv/bin/activate
uvicorn backend.api.main:app --reload
```

### Frontend

```bash
cd frontend
npm run dev
```

### CLI examples

```bash
python -m backend.cli config show
python -m backend.cli plan "Improve OSS self-hosting workflow"
python -m backend.cli repository context --query "config ollama cli"
```

---

## Docker Compose bootstrap

The repository ships a bootstrap Compose stack in `infrastructure/docker-compose.yml`.

Current characteristics:

- backend runs with `LLM_PROVIDER=stub` by default;
- frontend points to the local backend API;
- persistent backend data is stored in the `autodev_data` volume.

This keeps the default Compose story aligned with the OSS-first requirement. As of E0, a
production-like Compose profile (`--profile prod`) additionally wires PostgreSQL, Redis, and
MinIO/S3 into the platform path (see [`docs/ops/storage.md`](../ops/storage.md)); the
dependency-free stub + SQLite default above is preserved for local/CI use. An `observability`
profile (`make observability-up`) adds an OpenTelemetry Collector, Prometheus, Tempo, Loki,
and a provisioned Grafana dashboard (see [`docs/ops/observability.md`](../ops/observability.md)).

---

## Isolated execution environment (E32)

Real command execution runs inside a pluggable, fail-closed execution
environment: the default backend is a hardened container with no network,
no host filesystem beyond the workspace mount, and no ambient credentials
(ADR-013, Accepted). `AUTODEV_EXECUTION_ENVIRONMENT_BACKEND=unavailable`
acts as a config-level kill switch — it refuses execution outright rather
than degrading isolation. See
[`docs/v2_platform/phases/e32_isolated_execution_beta.md`](../v2_platform/phases/e32_isolated_execution_beta.md)
for the environment abstraction and lifecycle, and the `Validation sandbox`
and `Filesystem confinement` sections of [`docs/security.md`](../security.md)
for the wider execution security posture.

---

## Known gaps before production-grade self-hosting

Delivered as of the v2.0-beta wave (E0, E32-E35):

- PostgreSQL as the primary durable store — **landed (E0-S3)**, selected via `DATABASE_URL`;
- Redis-backed async execution — **landed (E0-S6)**;
- MinIO-backed artifact storage — **landed (E0-S6)**;
- OpenTelemetry, Prometheus, Grafana, and Loki integration — **landed (E0-S4)**
  (see [`docs/ops/observability.md`](../ops/observability.md));
- isolated, fail-closed execution environment for real command execution — **landed (E32)**;
- secrets and credential governance — **landed (E33)**;
- packaged CLI install, self-host preflight/bootstrap, and upgrade with
  schema-version compatibility checks — **landed (E34)**, see the two
  sections above.

Still open for production-grade self-hosting:

- persisted multi-repository policies;
- pgvector-backed semantic retrieval (`Semantic retrieval` in the feature
  matrix is still `planned`);
- infrastructure/docs CI validation (Compose/terraform lint, docs-link-check
  — `Infra / docs validation` in the feature matrix is still `planned`).

These items are tracked in [`docs/roadmap.md`](../roadmap.md).

> **Note on `docs/feature_matrix.md`:** at the time of this update, the
> feature matrix's "Isolated execution environment — Beta slice" and
> "Global install & upgrade" rows still read `planned`, referencing ADR-013
> and ADR-015 as pending. Both ADRs are Accepted and both epics (E32, E34)
> are Done per `docs/v2_platform/progress.md`; this guide reflects that
> landed state, verified directly against `docs/execution/cli-install.md`,
> `docs/execution/upgrade.md`, and the E32 phase document. The feature
> matrix itself was out of scope for this edit and should be refreshed in
> the next documentation-rebuild pass.
