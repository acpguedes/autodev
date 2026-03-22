# Current Weaknesses and Remediation Strategies

This document maps the current weaknesses of the repository to concrete strategies for evolving AutoDev Architect into a strong production-grade OSS platform.

---

## 1. In-memory state only

### Current weakness
Sessions and artifacts are stored in process memory.

### Risks
- data loss on restart;
- no horizontal scalability;
- no durable audit trail;
- no long-lived workflow resumption.

### Strategy
- move sessions, runs, messages, approvals, and artifacts metadata into PostgreSQL;
- use Redis only for ephemeral execution coordination;
- add run IDs and durable state transitions.

---

## 2. Linear fixed workflow

### Current weakness
The orchestrator executes a static sequence of agents.

### Risks
- no context-aware routing;
- no branch support for new project vs existing repository;
- no explicit approval gates;
- no retry or resume semantics.

### Strategy
- define a formal run state machine;
- add conditional routing based on request type and repository state;
- persist step-level state;
- support re-run of specific steps.

---

## 3. Stub-heavy agents

### Current weakness
Most agents return generic messages instead of specialized outputs.

### Risks
- low practical usefulness;
- gap between documentation and implementation;
- weak integration between agents.

### Strategy
- define structured outputs per agent;
- implement real repository intelligence, analysis, patching, and validation;
- separate narrative output from machine-readable output.

---

## 4. No repository intelligence system

### Current weakness
Navigation does not yet include AST, symbol, or semantic indexing.

### Risks
- poor context selection;
- high hallucination risk;
- inefficient patch generation.

### Strategy
- add tree-sitter indexing;
- store symbols and references in PostgreSQL;
- add pgvector embeddings for semantic retrieval;
- combine lexical + semantic + structural ranking.

---

## 5. No patch generation / application pipeline

### Current weakness
The system describes changes but does not generate/apply diffs.

### Risks
- cannot fulfill the core product promise;
- no reviewable code changes;
- impossible to validate end-to-end engineering workflows.

### Strategy
- introduce patch proposal schema;
- create patch validation and application layer;
- use isolated workspaces;
- persist patches and supporting rationale.

---

## 6. Validation is descriptive, not executable

### Current weakness
Validation outputs are static suggestions.

### Risks
- no trustworthy completion signal;
- no automatic rework loop;
- no evidence for quality claims.

### Strategy
- implement executable validation pipelines;
- capture logs, return codes, and artifacts;
- classify failures for automated retries.

---

## 7. No isolated execution environment

### Current weakness
There is no real sandbox runner in the platform workflow.

### Risks
- unsafe command execution;
- non-reproducible results;
- environment-specific flakiness.

### Strategy
- introduce Docker-based workspace runner;
- define per-repository command policy;
- store execution manifests and artifacts.

---

## 8. Limited frontend workflow support

### Current weakness
The UI is a chat demo, not an execution console.

### Risks
- human approval loop is missing;
- users cannot inspect run details deeply;
- platform differentiation is not visible.

### Strategy
- redesign UI around sessions, runs, approvals, patches, and validation artifacts;
- add live progress and event streaming;
- make the run timeline the primary interaction model.

---

## 9. Incomplete CI/CD and operational readiness

### Current weakness
CI focuses mostly on basic backend tests.

### Risks
- low confidence in broader system changes;
- frontend and infra regressions;
- docs drift.

### Strategy
- add frontend lint/typecheck/build;
- add infra validation;
- add docs checks and link validation;
- add container image build and security scanning.

---

## 10. Weak observability and governance

### Current weakness
The current implementation lacks strong telemetry, policies, and approvals.

### Risks
- difficult debugging;
- poor trust and auditability;
- limited organizational adoption.

### Strategy
- instrument traces and metrics using OpenTelemetry;
- persist audit events;
- implement approval and execution policies;
- expose operational dashboards.

---

## 11. Narrow model provider abstraction

### Current weakness
Current provider support is minimal.

### Risks
- strategic dependence on limited providers;
- weaker OSS positioning;
- reduced deployability for self-hosted teams.

### Strategy
- support open source local inference paths first;
- make model selection a policy and configuration concern;
- separate provider adapters from agent logic.

---

## 12. Documentation previously under-specified the path to production

### Current weakness
The earlier docs were strong on aspiration but lighter on implementation direction.

### Risks
- contributors lack a shared target;
- design drift across future changes;
- difficulty prioritizing work.

### Strategy
- maintain target architecture and implementation strategy docs;
- define stack decisions and rationale;
- document agent behavior contracts and governance principles.

