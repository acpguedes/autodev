# Roadmap

## North star

AutoDev Architect becomes an open source, self-hostable, patch-first GenAI engineering platform with planning, repository intelligence, validation, approvals, and observability.

---

## Release 0.1 - Prototype foundation

Focus:
- basic agent orchestration
- initial API
- chat demo UI
- deterministic fallbacks

Status:
- largely present in the repository today

---

## Release 0.2 - Durable platform core

Goals:
- PostgreSQL persistence
- Redis-backed background execution
- run state machine
- structured agent outputs
- improved API contracts

Current implementation status:
- durable sessions, runs, and message history are now persisted via a SQLite-backed bootstrap store;
- API endpoints expose session and run history for inspection;
- explicit run typing and persisted run-step history now provide the first workflow-state slice;
- PostgreSQL and Redis-backed async execution remain pending in the next slices.

Success criteria:
- sessions survive restart
- runs can be resumed and inspected
- UI can query history and statuses

---

## Release 0.3 - Repository intelligence

Current implementation status:
- run records now distinguish workflow types such as documentation, validation, devops, and existing-repository change;
- each run now persists ordered workflow steps, creating a bridge from the bootstrap durable control plane to a fuller state machine;
- a first repository-intelligence slice now exposes structured file inventory and ranked candidate-file retrieval via the navigator and `GET /repository/context`;
- typed metadata contracts are now published for every built-in agent via `GET /agents/contracts`, with fallback validation keeping machine-readable artifacts well-formed;
- tree-sitter indexing, deeper retrieval, and repository metadata storage remain the next major capability gap.

Goals:
- tree-sitter indexing
- lexical + semantic retrieval
- symbol discovery
- repository metadata storage

Success criteria:
- navigator returns relevant files/symbols for common tasks
- analyzer uses indexed evidence instead of generic summaries

---

## Release 0.4 - Patch and validation pipeline

Goals:
- patch proposal generation
- patch application service
- Docker sandbox runner
- executable validator

Success criteria:
- system can produce a patch for existing repositories
- validation artifacts are stored and viewable
- failures can feed rework loops

---

## Release 0.5 - Approval workflow and full UI

Current implementation status:
- the chat demo UI has been expanded into an initial execution control center;
- operators can now configure the active LLM provider and repository/workspace from the web UI;
- runtime settings are also persisted in a local JSON config file and exposed via `GET/PUT /config`;
- approval workflows, diff explorer, and artifact browsing remain the major missing slices.

Goals:
- plan approval
- patch approval
- run timeline UI
- diff view UI
- artifact and validation explorer

Success criteria:
- user can drive a complete run through the UI
- approvals are persisted and auditable

---

## Release 0.6 - OSS competitive platform

Current implementation status:
- a first OSS-competitive slice now includes a structured local CLI for config, planning, execution, and repository-context inspection;
- runtime configuration and the web UI now expose `ollama` as a first-class local-model path through an OpenAI-compatible endpoint;
- self-hosting guidance now documents local-only and hybrid startup paths built around the existing Docker Compose stack;
- observability dashboards, multi-repository policies, and broader CI coverage remain the next major gaps to close.

Goals:
- local model support as first-class path
- CLI
- self-hosting docs
- multi-repository policies
- observability dashboards
- stronger CI/CD and testing

Success criteria:
- self-hosted install succeeds with only open source dependencies
- project becomes viable as an OSS alternative in the GenAI coding workflow space

---

## Release 0.7 - Governance and policy control plane

Goals:
- persisted repository policy documents
- approval rules by run type and action category
- command allowlists for validation/sandbox execution
- audit events for configuration, approvals, and patch application
- workspace/repository switching with explicit active policy selection

Success criteria:
- operators can define policy without editing prompts
- sensitive actions are blocked or gated consistently across UI, API, and CLI
- every approval and policy decision is auditable

---

## Release 0.8 - Patch execution and sandbox validation

Goals:
- unified diff artifact model
- patch application service with rollback metadata
- Docker sandbox validation runner
- stored validation artifacts and logs
- automated rework loop from validator failures back into coding tasks

Success criteria:
- the platform can produce, apply, validate, and store a reviewable patch end-to-end
- failed validation emits structured evidence that can drive another iteration

---

## Release 0.9 - Observability and operations

Goals:
- OpenTelemetry instrumentation
- Prometheus metrics for runs, agents, and validation outcomes
- Grafana/Loki starter dashboards
- operator-facing run diagnostics in the UI
- CI coverage for backend, frontend, docs, and infrastructure checks

Success criteria:
- a self-hosted operator can inspect latency, failures, and throughput without prompt forensics
- dashboards and logs make workflow regressions obvious

---

## Release 1.0 - Team-ready OSS platform

Goals:
- PostgreSQL + Redis production path replacing bootstrap-only storage assumptions
- multi-repository tenancy and policy inheritance
- role-aware approvals and artifact governance
- documented production deployment on Docker Compose and Kubernetes
- contributor and operator documentation for serious OSS adoption

Success criteria:
- the platform is deployable as a credible OSS alternative for real engineering teams
- core planning, repository intelligence, patching, validation, governance, and observability flows work together in a reviewable control plane
