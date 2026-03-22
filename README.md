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
- durable session, run, and message persistence backed by a SQLite store for the first functional stage;
- agent abstraction layer;
- stub/fallback LLM integration;
- simple Next.js chat interface;
- local install script, Docker Compose stack, and initial CI/Terraform placeholders.

The documentation in this repository defines the path from prototype to a complete platform.

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
- [`docs/architecture/initial_architecture.md`](docs/architecture/initial_architecture.md): original early decisions for historical context.
- [`docs/architecture/target_architecture.md`](docs/architecture/target_architecture.md): target production architecture.
- [`docs/architecture/stack_decisions.md`](docs/architecture/stack_decisions.md): chosen stack and technical tradeoffs.
- [`docs/architecture/weaknesses_and_strategies.md`](docs/architecture/weaknesses_and_strategies.md): current weaknesses and remediation strategies.

### Implementation
- [`docs/implementation/implementation_strategy.md`](docs/implementation/implementation_strategy.md): detailed implementation strategy.
- [`docs/implementation/agent_spec.md`](docs/implementation/agent_spec.md): role definitions, contracts, and expected outputs for agents.
- [`docs/implementation/data_model.md`](docs/implementation/data_model.md): persistent data model and storage guidance.

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
3. Introduce an explicit run state machine and approval model.
4. Implement repository indexing using tree-sitter and pgvector.
5. Generate and validate patches in isolated workspaces.
6. Expand the UI from chat demo to execution control center.
7. Add complete CI for backend, frontend, docs, and infra.
8. Support open source local-model deployment modes.

---

## Development status

This repository is still in the transition from prototype to platform. The new documentation establishes the canonical direction for that transition.

## Running the first durable stage

### Local installation

1. Copy `.env.example` if you want to customize runtime variables.
2. Run `./scripts/install_dependencies.sh`.
3. Optionally adjust `DATABASE_URL` (the first functional stage uses SQLite by default).
4. Start the backend with `source .venv/bin/activate && uvicorn backend.api.main:app --reload`.
5. Start the frontend with `cd frontend && npm run dev`.

### Docker option

Run `docker compose -f infrastructure/docker-compose.yml up --build`.

This boots:
- FastAPI backend with a persisted SQLite database volume on `http://localhost:8000`;
- Next.js frontend on `http://localhost:3000`.

If you are contributing, start with:

1. `README.md`
2. `DESCRIPTION.md`
3. `docs/architecture/target_architecture.md`
4. `docs/implementation/implementation_strategy.md`
5. `AGENTS.md`

