# AutoDev Architect

> Open source platform for **planning, analyzing, patching, validating, and evolving software projects with GenAI agents**.

AutoDev Architect is an open source alternative for teams that want a transparent, extensible, and self-hostable system for **AI-assisted software delivery**. It is designed to compete in the category of tools such as Codex-style agents and cloud code assistants, while prioritizing:

- **open architecture**;
- **self-hosting**;
- **patch-based code changes**;
- **human approval workflows**;
- **observability and reproducibility**;
- **support for existing repositories and greenfield projects**.

The project currently contains an MVP skeleton. This repository now documents the **target architecture**, **recommended implementation strategy**, **chosen open source stack**, and **operational direction** required to evolve it into a solid production-grade platform.

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

The current codebase provides a functional early platform slice with:

- FastAPI backend orchestrator;
- durable session, run, and message persistence backed by a SQLite store (Repository pattern + adapters landed; PostgreSQL adapter is a scaffold stub);
- explicit run typing plus persisted workflow-step history for each execution;
- agent abstraction layer with typed metadata contracts published via the API;
- stub/fallback LLM integration (OpenAI and Ollama supported; Anthropic not yet implemented);
- first-class local-model configuration via `ollama` using an OpenAI-compatible local endpoint;
- structured local CLI support for config inspection, planning, run execution, and repository-context inspection;
- Next.js frontend with six pages (chat, config, agents, plans, skills, patches) — dark-theme only, no component library yet;
- post-analysis execution-plan generation that expands agent artifacts into ordered tasks — **note: `execute_plan()` is currently a mock that stamps tasks as completed without running real actions**;
- plans persist in a SQLite store with approve/reject API — **note: approval does not yet gate execution**;
- plugin-seam auto-discovery for API routers, agents, and CLI subcommands;
- local install script, Docker Compose stack (backend + frontend only), and initial CI.

See [`docs/feature_matrix.md`](docs/feature_matrix.md) for a precise `default / optional / stub / planned` breakdown of every feature.

The documentation in this repository defines the path from prototype to a complete platform.

---

## Platform subsystems (multi-agent, skills, plans)

The platform now ships an extensible, **plugin-seam** architecture: new endpoints, agents, and
CLI subcommands attach as self-contained modules via auto-discovery, without editing the core
files. See [`docs/architecture/plugin_seams.md`](docs/architecture/plugin_seams.md) for the
seams and the reserved-namespace table. Subsystems built on it:

- **Skills** — a discover/invoke registry with deterministic built-ins; `GET /skills`,
  `POST /skills/{name}/invoke`, and `autodev skills`. See
  [`docs/implementation/skills_subsystem.md`](docs/implementation/skills_subsystem.md).
- **Specialized agents + registry** — `security`/`refactor`/`docs` agents that self-register;
  `GET /agents`, `autodev agents list`.
- **Dynamic multi-agent orchestration** — run-type routing/supervisor graphs and an opt-in
  `POST /chat/dynamic` (flag `AUTODEV_DYNAMIC_ORCH=1`). See
  [`docs/implementation/dynamic_orchestration.md`](docs/implementation/dynamic_orchestration.md).
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

### Optional local model path
- **Inference gateway**: vLLM or Ollama
- **Embeddings**: local embedding models served through Ollama/vLLM or sentence-transformers services

For rationale, read [`docs/architecture/stack_decisions.md`](docs/architecture/stack_decisions.md).

---

## Documentation map

### Product and direction
- [`DESCRIPTION.md`](DESCRIPTION.md): strengthened product vision and positioning.
- [`docs/product/project_charter.md`](docs/product/project_charter.md): mission, users, principles, and success criteria.
- [`docs/roadmap.md`](docs/roadmap.md): phased roadmap from MVP to production platform.

### Architecture
- [`docs/architecture/v2_platform_reference.md`](docs/architecture/v2_platform_reference.md): **v2.0 platform reference** — full design of the customizable/extensible platform (plugins, agents, flows, reasoning, routing/selection/evaluation, skills, UI/UX) with a staged roadmap governed by functional/non-functional criteria and DoR/DoD.
- [`docs/architecture/initial_architecture.md`](docs/architecture/initial_architecture.md): original early decisions for historical context.
- [`docs/architecture/target_architecture.md`](docs/architecture/target_architecture.md): target production architecture.
- [`docs/architecture/stack_decisions.md`](docs/architecture/stack_decisions.md): chosen stack and technical tradeoffs.
- [`docs/architecture/weaknesses_and_strategies.md`](docs/architecture/weaknesses_and_strategies.md): current weaknesses and remediation strategies.

### Implementation
- [`docs/implementation/implementation_strategy.md`](docs/implementation/implementation_strategy.md): detailed implementation strategy.
- [`docs/implementation/self_hosting_oss.md`](docs/implementation/self_hosting_oss.md): OSS/self-hosted setup paths for stub, Ollama, and hybrid modes.
- [`docs/implementation/agent_spec.md`](docs/implementation/agent_spec.md): role definitions, contracts, and expected outputs for agents.
- [`docs/implementation/data_model.md`](docs/implementation/data_model.md): persistent data model and storage guidance.

### Implementation status
- [`docs/feature_matrix.md`](docs/feature_matrix.md): per-feature status (`default / optional / stub / planned`) covering persistence, LLM providers, agents, patches, validation, and more.
- [`CHANGELOG.md`](CHANGELOG.md): tagged releases, starting with `v1.0.0` — the v1 architecture baseline cut immediately before the v2.0 platform rewrite.

### Developer workflow
- [`Makefile`](Makefile): install, test, lint, build, run, and clean targets.
- [`docs/testing.md`](docs/testing.md): how to install, test, cover, lint, and reproduce CI locally.
- [`docs/security.md`](docs/security.md): threat model, hardening applied, and the environment flags that gate authentication, execution, and network exposure.

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

1. Replace in-memory state with PostgreSQL persistence.
2. Add Redis-backed async execution.
3. Expand the new workflow-state slice into a full explicit run state machine and approval model.
4. Implement repository indexing using tree-sitter and pgvector.
5. Generate and validate patches in isolated workspaces.
6. Expand the UI from chat demo to execution control center.
7. Add complete CI for backend, frontend, docs, and infra.
8. Support open source local-model deployment modes.

---

## Development status

This repository is still in the transition from prototype to platform. The new documentation establishes the canonical direction for that transition.

## Running the first durable stage

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
make run-backend    # FastAPI on http://localhost:8000 (separate terminal)
make run-frontend   # Next.js on http://localhost:3000
make build          # production build of the frontend
make clean          # remove all generated artifacts (git tree stays clean)
make help           # list every target
```

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
2. `docs/testing.md` (install, test, build, and CI-parity workflow)
3. `DESCRIPTION.md`
4. `docs/architecture/target_architecture.md`
5. `docs/implementation/implementation_strategy.md`
6. `AGENTS.md`
