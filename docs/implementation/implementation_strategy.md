# Implementation Strategy

This document defines the recommended implementation path for evolving AutoDev Architect from prototype to robust platform.

---

## Guiding strategy

Do not attempt to build every promised feature simultaneously. Instead, convert the current prototype into a reliable product by shipping complete vertical slices.

### Recommended build order

1. durable control plane;
2. explicit workflow state machine;
3. repository intelligence;
4. patch generation and patch application;
5. isolated validation;
6. approval and governance;
7. advanced UX and multi-model routing.

---

## Phase 1: Durable control plane

### Objectives
- replace in-memory session storage;
- create persistent run records;
- support resumable sessions;
- support async work dispatch.

### Deliverables
- PostgreSQL schema for sessions, runs, messages, approvals, artifacts, and audit events;
- Redis-backed queue;
- worker runtime;
- API endpoints for run creation, status, and history.

### Notes
This phase creates the foundation needed for all later features.

Current functional slice in this repository:
- durable session, run, and message persistence through a SQLite bootstrap store;
- resumable history across service restarts;
- API endpoints for run creation, session lookup, and run history;
- a clean path remains open for PostgreSQL/Redis in the next infrastructure slice.

---

## Phase 2: Explicit workflow engine

### Objectives
- move from a fixed chain to a state machine;
- distinguish run types and step states;
- support approval gates and retries.

### Deliverables
- run state model;
- step state model;
- conditional graph routing;
- retry policies;
- partial rerun support.

Current functional slice in this repository:
- runs now persist an explicit `run_type` classification and `current_state`;
- ordered `run_steps` records capture which workflow stages completed for each run;
- the synchronous LangGraph chain now emits machine-readable step history, leaving conditional routing, retries, and partial reruns for the next slice.

### Suggested run types
- `greenfield_bootstrap`
- `existing_repo_change`
- `documentation_update`
- `devops_change`
- `validation_only`

---

## Phase 3: Repository intelligence

### Objectives
- implement repository awareness beyond directory listing;
- improve context retrieval and patch precision.

### Deliverables
- file inventory job;
- tree-sitter parsing pipeline;
- symbol extraction tables;
- PostgreSQL FTS indexes;
- pgvector embeddings and retrieval API;
- repository context selection service.

### Retrieval strategy
Use layered retrieval:
1. lexical narrowing;
2. symbol-aware filtering;
3. semantic reranking;
4. final prompt context assembly.

---

## Phase 4: Structured agent outputs

### Objectives
- separate human-readable summaries from machine-readable control data.

### Deliverables
- JSON-schema or Pydantic contracts for each agent;
- validation of outputs;
- error handling for malformed outputs;
- UI rendering based on structured results.

### Example output domains
- planner: steps, assumptions, risks, acceptance criteria;
- navigator: candidate files, symbols, repository regions;
- analyzer: change plan, impacted areas, risk score;
- coder: patch proposal, file operations, test updates;
- validator: command runs, results, evidence, next actions.

---

## Phase 5: Patch pipeline

### Objectives
- make patch generation the core system capability.

### Deliverables
- patch proposal model;
- unified diff generation;
- patch application service;
- patch validation before execution;
- persistence for patches and patch versions.

### Rules
- prefer minimal diffs;
- prohibit broad rewrites unless explicitly justified;
- require traceability from requested change to produced patch.

---

## Phase 6: Sandbox execution and validation

### Objectives
- make validation real and reproducible.

### Deliverables
- Docker-based workspace runner;
- command policy model;
- validation pipeline executor;
- artifact capture;
- failure classification and feedback loop.

### Validation domains
- tests;
- lint;
- type checking;
- build;
- security scans;
- optional policy checks.

---

## Phase 7: UI and operator experience

### Objectives
- evolve the frontend from demo chat to run management console.

### Deliverables
- session/run overview screens;
- structured plan view;
- patch diff viewer;
- approval actions;
- live event timeline;
- validation evidence explorer;
- artifact download surfaces.

---

## Phase 8: Governance, security, and policy

### Objectives
- make the platform safe to operate in real organizations.

### Deliverables
- authn/authz;
- repository policies;
- execution command allowlists;
- approval requirements by action type;
- audit trails;
- secrets isolation model.

---

## Phase 9: Optimization and scale

### Objectives
- reduce cost and latency while improving quality.

### Deliverables
- prompt/context optimization;
- model routing policies;
- caching for retrieval and plans;
- historical fix memory;
- run analytics dashboards.

---

## Recommended engineering standards

- Pydantic schemas for API and internal machine-readable outputs.
- Typed run events for streaming.
- Clear repository policy files.
- Test pyramid across unit, integration, and E2E.
- ADR-style documentation for major architecture changes.

---

## Anti-patterns to avoid

- coupling business state to prompt text only;
- depending exclusively on one paid LLM provider;
- treating validation as advisory instead of executable;
- using large-context prompting as a substitute for repository intelligence;
- rewriting full files when targeted patches are possible;
- adding too many infrastructure systems before the workflow needs them.
