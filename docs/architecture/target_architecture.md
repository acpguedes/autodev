# AutoDev Architect Target Architecture

This document defines the target architecture for evolving AutoDev Architect from a prototype into a robust open source AI software engineering platform.

---

## Architecture goals

The architecture must:

- support greenfield and existing-repository workflows;
- persist all relevant execution state;
- execute long-running jobs asynchronously;
- support agent collaboration with explicit run states;
- enable repository intelligence and patch generation;
- validate changes in isolated sandboxes;
- expose results through UI, API, and future CLI surfaces;
- remain deployable with open source infrastructure.

---

## Architectural layers

## 1. Experience layer

User-facing interfaces:

- Web UI (Next.js)
- CLI
- REST API
- Streaming events / WebSocket or SSE

Responsibilities:

- create sessions and runs;
- submit goals and approvals;
- display plans, patches, validations, and artifacts;
- surface live execution state and history.

---

## 2. Control plane

Control plane services manage workflows and policies.

Components:

- FastAPI API service
- orchestration service
- policy/authorization service
- session and approval service
- artifact metadata service

Responsibilities:

- persist and query sessions, runs, approvals, and artifacts;
- translate user actions into workflows;
- publish execution jobs;
- enforce policies before sensitive actions;
- expose run status and results.

---

## 3. Workflow and agent runtime

The workflow runtime executes agent chains according to explicit state transitions.

Key design decisions:

- workflows are state machines, not informal prompt chains;
- every run has a `run_state` and `step_state`;
- the orchestrator routes work based on repository context and run intent;
- execution is asynchronous;
- retries and partial re-runs are supported.

Recommended states:

- `drafting_plan`
- `awaiting_plan_approval`
- `navigating_repository`
- `analyzing_change`
- `drafting_architecture`
- `drafting_patch`
- `awaiting_patch_approval`
- `running_validation`
- `awaiting_human_decision`
- `completed`
- `failed`
- `cancelled`

---

## 4. Repository intelligence layer

This layer transforms a repository into machine-usable context.

Capabilities:

- file inventory;
- symbol extraction;
- AST parsing using tree-sitter;
- lexical search using ripgrep;
- semantic memory using embeddings;
- dependency and reference graph extraction;
- test file discovery;
- docs and config discovery.

Recommended components:

- tree-sitter parsers per language
- PostgreSQL tables for repository metadata
- pgvector for semantic retrieval
- background indexing jobs

Indexes should include:

- files
- symbols
- imports/edges
- commits / run references
- embeddings for code blocks and documentation

---

## 5. Patch and execution layer

This layer is responsible for real changes and validation.

Capabilities:

- create isolated workspace copies;
- generate patches;
- apply patches;
- run validation commands;
- capture stdout/stderr;
- store test/build artifacts;
- classify failures for feedback loops.

Execution model:

1. Create a workspace from repository snapshot.
2. Materialize required context.
3. Generate patch proposal.
4. Validate patch structure.
5. Apply patch to workspace.
6. Run validation pipeline.
7. Persist results and artifacts.
8. Route failures back into analysis/coding steps.

---

## 6. Storage layer

### PostgreSQL
System of record for:

- sessions
- runs
- messages
- approvals
- agent outputs
- repository metadata
- validation reports
- policy records
- audit events

### Redis
Used for:

- background job queues
- task scheduling
- locks
- short-term state and cache
- rate limiting

### MinIO
Used for:

- logs
- build artifacts
- test reports
- patch snapshots
- exported run bundles

### pgvector
Used for:

- semantic retrieval over code and documentation
- memory lookups for prior successful fixes and patterns

---

## 7. Observability layer

Must provide:

- traces per run, agent, and validation step;
- metrics for latency, queue depth, failure rates, approval rates, and token/cost usage;
- logs with `session_id`, `run_id`, and `workspace_id` correlation.

Recommended stack:

- OpenTelemetry
- Prometheus
- Grafana
- Loki

---

## 8. Security and policy layer

The platform must control:

- which repositories can be modified;
- which commands can be run;
- which actions need approval;
- which models may be used;
- which secrets can be accessed.

Recommended policy domains:

- repository policy
- workspace policy
- execution policy
- model routing policy
- approval policy

---

## Reference workflow: existing repository evolution

1. User submits change request.
2. Planner creates structured plan.
3. Human reviews plan if required.
4. Navigator indexes/retrieves relevant repo context.
5. Analyzer produces structured change plan.
6. Coder drafts patch proposal.
7. Human reviews patch if required.
8. Validator runs tests/build/lint/security in sandbox.
9. If successful, system packages outputs for PR/merge flow.
10. If failed, orchestrator loops back with validation evidence.

---

## Reference workflow: greenfield creation

1. User submits product/service goal.
2. Planner creates execution plan.
3. Architect drafts solution blueprint.
4. Coder generates project scaffold and tests.
5. DevOps generates container and CI assets.
6. Validator executes checks.
7. Outputs are packaged as repository bootstrap artifacts.

---

## Decision summary

### Chosen primary stack
- FastAPI for API and control plane.
- LangGraph for workflow graph orchestration.
- PostgreSQL + pgvector for persistence and semantic memory.
- Redis for queue, cache, locks, and event coordination.
- MinIO for artifacts.
- tree-sitter for repository intelligence.
- Next.js for UI.
- Docker/Kubernetes for sandboxing and deployment.
- OpenTelemetry + Prometheus + Grafana + Loki for observability.

### Why this stack
It is open, mature, widely adopted, self-hostable, and supports the project's need for both structured systems engineering and AI-driven workflows.

