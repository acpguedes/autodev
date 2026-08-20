# AutoDev Architect

> Open source platform for **planning, analyzing, patching, validating, and evolving software projects with GenAI agents**.

AutoDev Architect is an open source alternative for teams that want a transparent, extensible, and self-hostable system for **AI-assisted software delivery**. It is designed to compete in the category of tools such as Codex-style agents and cloud code assistants, while prioritizing:

- **open architecture**;
- **self-hosting**;
- **patch-based code changes**;
- **human approval workflows**;
- **observability and reproducibility**;
- **support for existing repositories and greenfield projects**.

The **v1 architecture** (linear agent pipeline) is frozen at the published [`v1` release](https://github.com/acpguedes/autodev/releases/tag/v1); its documentation is archived under [`docs/archive/v1/`](docs/archive/v1/README.md). The **v2.0 platform rewrite** — a small core surrounded by typed extension points (plugins, agents, flows, reasoning, routing, skills) — has completed its **Beta wave** ([`v2.0-beta`](https://github.com/acpguedes/autodev/releases/tag/v2.0-beta), pre-release): 22 epics and 95 stories, covering orchestration, reasoning, routing, skills, context/RAG, persistence, APIs, UI, security, real governed execution, isolated execution, secret governance, and global install. Three Beta exit criteria remain open — see [Beta status](#beta-status-and-known-gaps). GA (Marketplace, E13) is not started. [`docs/v2_platform/progress.md`](docs/v2_platform/progress.md) is the live tracker.

---

## Vision

AutoDev Architect should become a platform that can:

1. Understand a product request or engineering task.
2. Create an execution plan with explicit approval gates.
3. Inspect an existing repository using syntax-aware and semantic analysis.
4. Propose minimal, auditable patches.
5. Execute validation in an isolated sandbox.
6. Iterate on failures using agent feedback loops.
7. Produce artifacts such as docs, tests, CI/CD, infra, and pull requests.
8. Preserve traceability for every decision, prompt, patch, validation result, and approval.

This makes the project suitable for:

- engineering teams building internal developer platforms;
- OSS maintainers that want AI-assisted contribution workflows;
- enterprises that need self-hosted GenAI coding systems;
- research and experimentation around multi-agent software engineering.

---

## Product principles

- **Open source first**: all core platform capabilities should be buildable and operable with open source components.
- **Human in the loop**: plans, patches, and deployments must support approval gates.
- **Deterministic where possible**: use structured outputs, schemas, and verifiable execution instead of free-form text only.
- **Patch, not rewrite**: prefer minimal diffs over large file rewrites.
- **Observability by default**: every run must be inspectable.
- **Self-hostable architecture**: local, Docker, and Kubernetes deployments should be supported.
- **Provider flexibility**: the system should work with hosted and local models, but never depend on a paid provider to function.

---

## Current repository status

The repository holds two architecture generations: the frozen **v1 baseline** (the `v1`
release tag, documentation archived in [`docs/archive/v1/`](docs/archive/v1/README.md))
and the **v2 platform**, whose Beta wave is complete. See
[`docs/v2_platform/progress.md`](docs/v2_platform/progress.md) for the epic-by-epic
tracker and [`docs/feature_matrix.md`](docs/feature_matrix.md) for a precise
`default / optional / stub / planned` breakdown of every feature.

### v2 platform — Beta wave complete

**Core and extensibility**

- **E0 — Foundations**: containerized backend dev/test runtime; typed declarative
  settings with local/prod profiles and fail-fast validation; PostgreSQL-backed
  sessions/runs/messages/plans selected via `DATABASE_URL`; OpenTelemetry spans +
  Prometheus counters; HTTP security headers and a CI secret-scan/SCA gate; Redis
  queue/cache/locks and local/MinIO artifact stores.
- **E1 — Plugin Core & SDK**: `plugin.yaml` manifest schema + extension-point catalog;
  Plugin Host discovery and durable install/enable/disable lifecycle; default-deny
  fs/net/exec/secrets permissions with brokered Host API access; Python SDK with
  `sdk new plugin` scaffolding and a contract-test harness.
- **E2 — Agent Framework**: versioned `agent.yaml` manifests with typed IO; durable
  Agent Registry with SemVer resolution; Agent Runtime with fail-closed
  token/cost/step/tool budgets and output guardrails; permissioned tool/skill mediation
  and a provider abstraction.
- **E6 — Skills v2**: `skill.yaml` spec, Skill Registry with versioning, least-privilege
  invocation through the Agent Runtime, and skill composition.

**Orchestration and intelligence**

- **E3 — Orchestration Engine**: `flow.yaml` declarative graphs; durable Run/Step
  execution; checkpointing, retries and deterministic replay; human-in-the-loop nodes;
  sub-flow and map/reduce composites.
- **E4 — Reasoning**: pluggable Reasoning Strategy extension point with ReAct,
  Plan-and-Execute, Reflection and Debate/ToT strategies, under policies and budgets.
- **E5 — Routing, Selection & Evaluation**: Router (intent/task classification),
  Selector (agent/model/strategy by policy and cost), Evaluation Service, and an
  eval → routing feedback loop.
- **E7 — Context & RAG**: tree-sitter indexing pipeline, pgvector embeddings, hybrid
  lexical + vector retrieval, and pluggable Context Providers.

**Execution and governance**

- **E14 — Real Task Execution & Governed Autonomy**: real task executor; permission and
  policy engine; Approval/Auto/Hybrid execution modes; sandbox-backed runners; Web UX
  for governed execution; governed interactive shell (`autodev --shell`); `autodev` CLI.
- **E32 — Isolated Execution Environment**: execution-environment abstraction with an
  audited backend decision; fail-closed network and filesystem policy; environment
  lifecycle and workspace provisioning; isolation audit trail.
- **E33 — Secrets & Credential Governance**: secret store abstraction; injection into
  execution environments with redaction; rotation, revocation and audit.
- **E11 — Observability, Security & Multi-tenant**: OpenTelemetry traces/metrics/logs;
  RBAC and authentication; per-tenant quotas and run budgets; execution-security
  hardening and incident runbooks.

**Data, API, UI and quality**

- **E8 — Persistence & Data**: multi-tenant model with mandatory `tenant_id` scoping and
  PostgreSQL RLS; Event Store; MinIO Artifact Store with reference-based GC;
  backup/restore with RPO/RTO procedures.
- **E9 — APIs, Events & MCP**: Control Plane API `/v2`; run streaming; event catalog and
  Event Bus; MCP interoperability.
- **E10, E15–E18 — UI**: design system and tokens; design language v2 and the Execution
  Control Center shell; `/v2` contract parity; Control Center screens (chat, plans with
  step-level approval gates, patches review, sessions/config, extensions hub, flow
  builder); API front door and a single-command run experience.
- **E12 — Quality & Evals**: test pyramid and coverage gate; contract tests for every
  extension point; agent evals with a closed feedback loop; CI gates that block merges.
- **E34 / E35 — Packaging & readiness**: install strategy, self-host bootstrap, upgrade
  path with schema-version compatibility; 12-criterion Beta evidence map, acceptance
  flow, decision/risk registers, and incident runbooks.

### Beta status and known gaps

`v2.0-beta` is published as a **pre-release**. Of the twelve Beta exit criteria, seven
are met with citable evidence, two are partial, and three are open. They are named here
rather than rounded up; the full evidence map is
[`docs/v2_platform/beta_gap_analysis.md`](docs/v2_platform/beta_gap_analysis.md) §11.

| Gap | Status | Why |
| --- | --- | --- |
| Hybrid retrieval p95 < 300 ms + recall baseline | **Open** | Harness exists (`scripts/benchmark_retrieval.py`); no recorded run against a live environment. |
| Run streaming starts < 1 s | **Open** | Functional correctness tested; no test asserts a numeric latency bound. |
| Backup/restore RPO ≤ 5 min / RTO ≤ 30 min | **Open** | No staging environment; validated via a documented procedure only. |
| End-to-end plan → patch → validate → evaluate | **Partial** | Every component individually evidenced; no single composed automated rehearsal. See [`beta_acceptance_flow.md`](docs/v2_platform/beta_acceptance_flow.md). |
| WCAG 2.2 AA on key screens | **Partial** | Component-level coverage via Storybook-axe; no consolidated per-screen audit. |

Closing the three open items needs a live environment; that work is GA-wave, tracked in
[`docs/v2_platform/progress.md`](docs/v2_platform/progress.md).

### v1 baseline (frozen at the `v1` release tag)

v1 was a fixed linear agent pipeline
(Navigator → Analyzer → Architect → Coder → DevOps → Validator → Responder) with a
FastAPI backend, SQLite persistence, a six-page Next.js frontend, and mock plan
execution. Its documentation is archived, with a full v1 → v2 map, in
[`docs/archive/v1/README.md`](docs/archive/v1/README.md).

---

## Platform subsystems (multi-agent, skills, plans)

> **Note:** the subsystems below are the **v1** generation. The v1 plugin-seam
> auto-discovery mechanism is the informal precursor to the contracted v2 Plugin Host
> (`plugin.yaml` manifests, default-deny permissions, `/v2/plugins/active`) delivered by
> E1, and the v1 agents are the precursor to the E2 Agent Framework
> (`agent.yaml`, Agent Registry, budgeted Agent Runtime). See
> [`docs/plugins/`](docs/plugins/) and [`docs/agents/`](docs/agents/) for the v2 docs.

The v1 platform ships an extensible, **plugin-seam** architecture: new endpoints, agents, and
CLI subcommands attach as self-contained modules via auto-discovery, without editing the core
files. See [`docs/archive/v1/plugin_seams.md`](docs/archive/v1/plugin_seams.md) for the
seams and the reserved-namespace table. Subsystems built on it:

- **Skills** — a discover/invoke registry with deterministic built-ins; `GET /skills`,
  `POST /skills/{name}/invoke`, and `autodev skills`. See
  [`docs/archive/v1/skills_subsystem.md`](docs/archive/v1/skills_subsystem.md).
- **Specialized agents + registry** — `security`/`refactor`/`docs` agents that self-register;
  `GET /agents`, `autodev agents list`.
- **Dynamic multi-agent orchestration** — run-type routing/supervisor graphs and an opt-in
  `POST /chat/dynamic` (flag `AUTODEV_DYNAMIC_ORCH=1`). See
  [`docs/archive/v1/dynamic_orchestration.md`](docs/archive/v1/dynamic_orchestration.md).
- **Plans with approval gates** — a persisted plan store; `GET/PUT /plans/{session_id}`,
  `POST /plans/{session_id}/approve|reject`, and `autodev plans`.
- **Patch generation & application** — unified-diff engine, dry-run by default; `POST
  /patches/generate|apply`, `autodev patches`.
- **Validation sandbox** — flag-gated Docker/local runner; `POST /validation/run`,
  `autodev validate`.
- **Repository intelligence providers** — pluggable lexical/tree-sitter symbol extraction;
  `GET /repository/symbols`.
- **Observability** — request tracing + `GET /metrics` (Prometheus text).
- **Async jobs** — in-process queue (optional Redis backend); `POST /jobs`, `GET /jobs/{id}`.

Patches, validation, dynamic orchestration, the tree-sitter provider, and the Redis job
backend are **disabled by default behind environment flags**, and their optional dependencies
are kept out of `backend/requirements.txt`. See
[`docs/implementation/patches_and_validation.md`](docs/implementation/patches_and_validation.md).

---

## Target capabilities

### Core platform
- Multi-step planning with approval workflow.
- Repository navigation using AST, symbols, embeddings, and lexical search.
- Change analysis and impact assessment.
- Patch generation and patch application.
- Validation with tests, lint, typecheck, security, and build steps.
- Execution history, reproducibility, and rollback support.

### Collaboration and governance
- Session persistence.
- Audit trails.
- Role-based approvals.
- Multi-workspace support.
- Artifact retention.
- Explainability for decisions and generated changes.

### Developer experience
- CLI and Web UI.
- Real-time streaming updates.
- Pull request generation.
- Local model support.
- Configurable policies per repository.
- Reusable agent skills and templates.

---

## Recommended target stack

AutoDev Architect is intended to be fully operable with open source infrastructure.

### Application layer
- **Backend API**: FastAPI
- **Workflow orchestration**: LangGraph
- **Background jobs**: Celery or ARQ backed by Redis
- **Frontend**: Next.js
- **Typed contracts**: Pydantic + JSON Schema

### State and memory
- **System of record**: PostgreSQL
- **Vector search / long-term semantic memory**: PostgreSQL + pgvector
- **Hot cache / short-lived state / locks / queues**: Redis
- **Artifact storage**: MinIO (S3-compatible, open source)

### Code intelligence
- **Syntax parsing**: tree-sitter
- **Lexical search**: ripgrep + PostgreSQL full-text search
- **Repository metadata graph**: PostgreSQL tables + symbol index

### Execution and isolation
- **Sandbox execution**: Docker containers
- **Local orchestration**: Docker Compose
- **Production orchestration**: Kubernetes

### Observability
- **Tracing**: OpenTelemetry
- **Metrics**: Prometheus
- **Dashboards**: Grafana
- **Logs**: Loki
- **Available now** (E11-S1): self-hosted three-signal stack and dashboard
  via `make observability-up|verify|down` — see
  [`docs/ops/observability.md`](docs/ops/observability.md).

### Authentication & RBAC
- **Identity**: delegated to an external OIDC provider (authorization-code + PKCE)
- **Machine credentials**: governed, hash-only service keys
- **Authorization**: canonical five-role RBAC (`viewer`…`owner`) enforced on every `/v2` route
- **Available now** (E11-S2): local zero-config access is unchanged; production requires
  OIDC or a service credential — see [`docs/security.md`](docs/security.md).

### Optional local model path
- **Inference gateway**: vLLM or Ollama
- **Embeddings**: local embedding models served through Ollama/vLLM or sentence-transformers services

For rationale, read [`docs/archive/v1/stack_decisions.md`](docs/archive/v1/stack_decisions.md).

---

## Documentation map

### Product and direction
- [`DESCRIPTION.md`](DESCRIPTION.md): strengthened product vision and positioning.
- [`docs/product/project_charter.md`](docs/product/project_charter.md): mission, users, principles, and success criteria.
- [`docs/roadmap.md`](docs/roadmap.md): phased roadmap from MVP to production platform.

### Architecture
- [`docs/architecture/v2_platform_reference.md`](docs/architecture/v2_platform_reference.md): **v2.0 platform reference** — full design of the customizable/extensible platform (plugins, agents, flows, reasoning, routing/selection/evaluation, skills, UI/UX) with a staged roadmap governed by functional/non-functional criteria and DoR/DoD.
- [`docs/architecture/weaknesses_and_strategies.md`](docs/architecture/weaknesses_and_strategies.md): current weaknesses and remediation strategies, checked off per epic.
- [`docs/archive/v1/README.md`](docs/archive/v1/README.md): **archived v1 architecture** — what v1 was and which v2 subsystem replaced each document (initial architecture, target architecture, stack decisions, plugin seams).

### Implementation
- [`docs/implementation/self_hosting_oss.md`](docs/implementation/self_hosting_oss.md): OSS/self-hosted setup paths for stub, Ollama, and hybrid modes.
- [`docs/implementation/patches_and_validation.md`](docs/implementation/patches_and_validation.md): patch engine, validation sandbox, and the environment flags that gate them.
- [`docs/v2_platform/agent_guide.md`](docs/v2_platform/agent_guide.md): how to pick up and execute an `E<n>-S<m>` story.
- Superseded v1 implementation docs (agent spec, data model, implementation strategy, dynamic orchestration, skills subsystem, MVP refactor plan) are archived in [`docs/archive/v1/`](docs/archive/v1/README.md).

### Implementation status
- [`docs/feature_matrix.md`](docs/feature_matrix.md): per-feature status (`default / optional / stub / planned`) covering persistence, LLM providers, agents, patches, validation, and more.
- [`CHANGELOG.md`](CHANGELOG.md): tagged releases — `v1` (architecture baseline) and `v2.0-beta` (the v2 platform Beta wave, with its known limitations).
- [`docs/v2_platform/beta_gap_analysis.md`](docs/v2_platform/beta_gap_analysis.md): the 12-criterion Beta exit evidence map (fact vs. recommendation).

### Developer workflow
- [`Makefile`](Makefile): install, test, lint, build, run, and clean targets.
- [`docs/testing.md`](docs/testing.md): how to install, test, cover, lint, and reproduce CI locally.
- [`docs/security.md`](docs/security.md): threat model, hardening applied, and the environment flags that gate authentication, execution, and network exposure.
- [`docs/ops/observability.md`](docs/ops/observability.md): self-hosted OpenTelemetry + Prometheus + Tempo + Loki + Grafana stack — `make observability-up|verify|down`, span/metric naming, log schema, retention, and rollback.

### Governance and contribution
- [`AGENTS.md`](AGENTS.md): repository-wide instructions for autonomous coding agents.
- [`AGENT.md`](AGENT.md): project-level agent operating guide.
- [`CLAUDE.md`](CLAUDE.md): assistant-specific guidance compatible with Claude-style workflows.

---

## High-level target architecture

```text
User / API Client / CLI / Web UI
                |
                v
        FastAPI Control Plane
                |
                v
      Orchestrator / Policy Engine
                |
      +---------+---------+
      |                   |
      v                   v
Plan / Approval      Execution Queue (Redis)
State (Postgres)            |
                             v
                    Worker / Agent Runtime
                             |
           +-----------------+-----------------+
           |        |         |        |        |
           v        v         v        v        v
       Planner  Navigator  Analyzer  Coder  Validator
                             |                 |
                             +--------+--------+
                                      |
                                      v
                           Sandbox / Workspace Runner
                                      |
               +----------------------+----------------------+
               |                      |                      |
               v                      v                      v
          Git patch store       Validation artifacts   Observability stack
      (Postgres + MinIO)        (MinIO + Postgres)    (OTel/Prom/Grafana)
```

---

## What “production ready” means for this project

A production-ready AutoDev Architect release should include:

- persistent sessions and execution history;
- real repository indexing;
- structured change plans and patch generation;
- isolated validation execution;
- approval workflows;
- metrics, logs, and traces;
- policy controls and security boundaries;
- documentation and contributor guidance;
- self-hosting instructions;
- automated tests for backend, frontend, and infrastructure.

---

## Repository goals for the next major milestone

The eight goals that defined the previous milestone all shipped during the Alpha and
Beta waves: PostgreSQL persistence, Redis-backed async execution, an explicit run state
machine with an approval model, tree-sitter + pgvector repository indexing, patch
generation and validation in isolated workspaces, the Execution Control Center UI, CI
for backend/frontend/docs/infra, and local-model deployment modes.

The next milestone is **GA (E13 — Marketplace & GA)**:

1. Verified plugin publish/install end to end (signature + SBOM).
2. Control Plane SLO 99.9% and read p95 < 300 ms under load.
3. RPO ≤ 5 min / RTO ≤ 30 min proven in a real environment.
4. Close the three open Beta exit criteria (retrieval benchmark, streaming latency, staging restore).
5. Documented and tested v1 → v2 upgrade path.
6. GA checklist signed off across SLOs, security, docs, backups, and evals.

---

## Development status

The v2 platform rewrite has completed its **Beta wave** — 22 epics, 95 of 178 planned
stories. `v2.0-beta` is published as a pre-release with three exit criteria still open
(see [Beta status and known gaps](#beta-status-and-known-gaps)). The remaining waves are
GA (E13 — Marketplace) and the planned v2.1–v2.3 epics (E20–E31, E36–E40).
[`docs/v2_platform/progress.md`](docs/v2_platform/progress.md) is the authoritative
tracker; [`CONTRIBUTING.md`](CONTRIBUTING.md) defines the branching and quality workflow
for new work.

## Running the first durable stage

### Quickstart (UI + API)

The fastest way to run the whole product — the Control Center UI plus the
control-plane API — is a single command:

```bash
make install   # once: create .venv, install backend + frontend dependencies
make run       # backend on :8000 + frontend on :3000; Ctrl-C stops both
```

Then open **<http://localhost:3000>** — that is the AutoDev Control Center.
Prefer containers? `make container-up-full` boots the same pair with Docker
Compose.

| Port | Service | What you get |
| --- | --- | --- |
| 3000 | Frontend (Next.js) | The product UI — the Control Center |
| 8000 | Backend (FastAPI) | The `/v2` API, `GET /` service descriptor, `/docs` |
| 8001 | Backend (prod profile) | Optional `backend-prod` compose service |
| 5432 / 6379 / 9000-9001 | Postgres / Redis / MinIO | Optional compose profiles |

The backend origin (`:8000`) is **API only**: browsing it shows a service
descriptor that points at the UI — it never renders the product interface.

### Container-first quickstart

E0 v2 platform work runs backend tests and CLI commands inside the backend
container. The image owns the Python runtime and `.venv`, so the host does not
need a project virtualenv for E0 validation.

```bash
make container-build   # build the backend dev/test image
make container-up      # boot FastAPI on http://localhost:8000
make container-test    # run backend pytest inside the container
make container-check   # run backend lint + typecheck + tests inside the container
make container-shell   # open an interactive backend container shell
make container-down    # stop and remove the Compose stack
```

The backend container mounts the source tree paths needed for backend work,
stores SQLite/config state under the `autodev_data` volume, uses
`LLM_PROVIDER=stub`, and sets `AUTODEV_PROFILE=local` by default. Inside the
shell, run CLI commands as `python -m backend.cli ...`.

### Quickstart with `make`

The root [`Makefile`](Makefile) wraps install, test, build, run, and clean
flows. Targets use the project virtualenv (`.venv`) directly, so you never need
to activate it by hand:

```bash
make install        # create .venv, install backend + frontend dependencies
make test           # run the full backend (pytest) + frontend (vitest) suites
make run            # backend (:8000) + frontend (:3000) together (alias: make dev)
make build          # production build of the frontend
make clean          # remove all generated artifacts (git tree stays clean)
make help           # list every target
```

#### API only / headless

If you only need the control-plane API (scripts, MCP clients, curl), start the
backend alone with `make run-backend` (or `uvicorn backend.api.main:app
--reload`). Keep the model in mind: the backend serves the **API** on `:8000`;
the product UI is the separate Next.js app on `:3000`. Browsing
`http://localhost:8000/` returns a service descriptor (JSON for API clients, a
pointer page for browsers) — not the product UI — and the interactive API
reference lives at `http://localhost:8000/docs`.

### Troubleshooting: "I opened localhost:8000 and see JSON / 404 / a blank /docs"

AutoDev is two processes: the FastAPI **API** on `:8000` and the Next.js
**Control Center UI** on `:3000`. Seeing raw JSON on `:8000` means the API is
healthy — the product UI simply lives at <http://localhost:3000>. Start both
with `make run` (or `make container-up-full`).

Symptoms on **older checkouts** (fixed by E18 — `git pull` and rerun):

- `GET /` returned **404** — there was no root route; it now serves a service
  descriptor that links to the UI, `/docs`, and `/health`.
- `GET /docs` rendered a **blank page** — Swagger UI was loaded from a CDN
  with an inline script, both blocked by the strict Content-Security-Policy;
  the docs are now self-hosted and CSP-clean (and work fully offline).

Every artifact these targets produce is git-ignored, so `make install`/`make
test`/`make build` never dirty your working tree. Full instructions for
testing, coverage, linting, CI parity, and cleanup live in
[`docs/testing.md`](docs/testing.md).

### Local installation

1. Copy `.env.example` if you want to customize runtime variables: `cp .env.example .env`.
2. Run `./scripts/install_dependencies.sh` with Python 3.10+ available as `python3` (or override `PYTHON_BIN`).
3. Adjust `DATABASE_URL` if you want to move the bootstrap durable store away from the default SQLite file.
4. Configure the agent API / LLM provider:
   - keep `LLM_PROVIDER=stub` for fully local deterministic fallback behavior; or
   - set `LLM_PROVIDER=openai` and fill `OPENAI_API_KEY`, plus optional `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_TEMPERATURE`.
   - set `LLM_PROVIDER=ollama` for a local-model path and optionally override `OLLAMA_BASE_URL` (defaults to `http://localhost:11434/v1`).
5. Start the backend with `source .venv/bin/activate && uvicorn backend.api.main:app --reload`.
6. Start the frontend with `cd frontend && npm run dev`.
7. Optionally use the structured CLI:
   - `python -m backend.cli config show`
   - `python -m backend.cli plan "Improve local OSS workflow"`
   - `python -m backend.cli repository context --query "config cli ollama"`

### OSS self-hosting quick paths

#### Fully local deterministic mode
- Backend: `LLM_PROVIDER=stub uvicorn backend.api.main:app --reload`
- Frontend: `cd frontend && npm run dev`
- CLI: `python -m backend.cli config show --format env`

#### Local-model mode with Ollama
1. Run Ollama locally and expose its OpenAI-compatible endpoint.
2. Set `LLM_PROVIDER=ollama`.
3. Set `OPENAI_MODEL` or save the model name in `autodev.config.json` through the UI/CLI.
4. Optionally set `OLLAMA_BASE_URL` if your local gateway is not `http://localhost:11434/v1`.

#### Docker Compose bootstrap
- Start the current stack with `docker compose -f infrastructure/docker-compose.yml up --build`.
- The compose file keeps the backend on the open-source `stub` path by default so the platform can boot without paid infrastructure.

For a fuller operator checklist, read [`docs/implementation/self_hosting_oss.md`](docs/implementation/self_hosting_oss.md).

### Runtime configuration center

The web UI now includes a configuration panel for:

- choosing the LLM provider and model settings;
- storing an API key and optional compatible base URL;
- selecting the active repository/workspace root directory;
- defining the default planning goal used when creating a new session.

The backend persists this runtime state in `autodev.config.json` by default. Use `AUTODEV_CONFIG_PATH` if you want to store the file elsewhere. A tracked starter template is available at [`autodev.config.example.json`](autodev.config.example.json).

### Configuring the agent API

The backend defaults to a `stub` provider so the platform remains self-hostable even without a paid model API. When you want live LLM-backed agent behavior, export these variables before starting the backend:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=your_key_here
export OPENAI_MODEL=gpt-4o-mini
# Optional when using a compatible gateway or proxy
export OPENAI_BASE_URL=
export OPENAI_TEMPERATURE=0.2
```

If `LLM_PROVIDER=openai` is set without `OPENAI_API_KEY`, the backend falls back to the deterministic stub model instead of crashing.

### Configuring via file or environment

You can configure the same settings without the UI:

1. Copy `autodev.config.example.json` to `autodev.config.json`.
2. Adjust `llm` and `repository.project_root` for your environment.
3. Restart the backend, or update the settings through `PUT /config`.

If you prefer environment variables, keep using `.env` / shell exports for `LLM_PROVIDER`, `OPENAI_*`, and `AUTODEV_PROJECT_ROOT`. The configuration page shows both JSON and `.env` examples so operators can choose the workflow that fits their deployment model.

When the Next.js UI runs locally on `http://localhost:3000`, it now defaults API requests to `http://localhost:8000`. Set `NEXT_PUBLIC_API_URL` explicitly if your backend is hosted elsewhere or fronted through a different origin.

### Repository context API

The first repository-intelligence slice now exposes `GET /repository/context`, which returns a structured inventory summary plus ranked candidate files for a query. Example:

```bash
curl "http://localhost:8000/repository/context?query=agent%20api&limit=5"
```

This endpoint is intended to seed later tree-sitter, FTS, and vector-based retrieval work with an explicit machine-readable contract.

### Docker option

Run `docker compose -f infrastructure/docker-compose.yml up --build`.

This boots:
- FastAPI backend with a persisted SQLite database volume on `http://localhost:8000`;
- Next.js frontend on `http://localhost:3000`.

If you are contributing, start with:

1. `README.md`
2. `CONTRIBUTING.md` (branching model, coding standards, testing policy)
3. `docs/testing.md` (install, test, build, and CI-parity workflow)
4. `docs/v2_platform/progress.md` (where the v2 platform rewrite stands)
5. `docs/v2_platform/agent_guide.md` (story workflow for the v2 epics)
6. `AGENTS.md`

---

## License and citation

AutoDev Architect is released under the **Apache License 2.0** — see
[`LICENSE`](LICENSE). Redistribution, including commercial products and
services built on this project, must retain the attribution in
[`NOTICE`](NOTICE), as required by Section 4 of the license.

If you use this project in academic or published work, please cite it using
the metadata in [`CITATION.cff`](CITATION.cff) (GitHub's "Cite this
repository" button is backed by that file).
