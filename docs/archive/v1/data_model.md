# Data Model Direction

> **Archived 2026-08-20 — v1 architecture.** This document describes the v1
> linear-pipeline design, frozen at the
> [`v1` release](https://github.com/acpguedes/autodev/releases/tag/v1).
> Superseded by E8's multi-tenant model and migrations — see [`docs/architecture/v2_platform_reference.md`](../../architecture/v2_platform_reference.md) §13 and [`docs/ops/storage.md`](../../ops/storage.md).
> Retained as the design audit trail; **not maintained**. See
> [`docs/archive/v1/README.md`](README.md) for the full v1 -> v2 map.

This document defines the recommended persistent model for AutoDev Architect.

---

## Primary entities

### Workspace
Represents a logical project space or tenant boundary.

### Repository
Represents a code repository managed by the platform.

### Session
Represents a user conversation or initiative over time.

### Run
Represents one executable workflow instance.

### RunStep
Represents an individual step/state transition inside a run.

Current bootstrap slice:
- SQLite now persists `runs.current_state`, `runs.run_type`, and ordered `run_steps` records so workflow progress survives restarts before the PostgreSQL migration.

### Message
Stores conversational and system messages.

### Approval
Stores explicit user or policy approvals.

### AgentResult
Stores narrative and structured outputs from an agent.

### Patch
Stores generated diff proposals and versions.

### ValidationExecution
Stores executed commands and their outcomes.

### Artifact
Stores metadata for files persisted in object storage.

### AuditEvent
Stores significant security, workflow, and policy events.

---

## Suggested storage mapping

### PostgreSQL tables
- `workspaces`
- `repositories`
- `repository_snapshots`
- `sessions`
- `runs`
- `run_steps`
- `messages`
- `approvals`
- `agent_results`
- `patches`
- `patch_files`
- `validation_executions`
- `validation_command_results`
- `artifacts`
- `audit_events`
- `repository_files`
- `repository_symbols`
- `repository_edges`
- `embedding_documents`

### Redis keys / structures
- run queue
- indexing queue
- workspace locks
- rate limits
- short-lived caches

### MinIO buckets
- patch-artifacts
- validation-artifacts
- run-exports
- logs

---

## Design rules

- durable truth lives in PostgreSQL;
- artifacts live in MinIO, referenced by metadata rows;
- Redis stores ephemeral state only;
- vector embeddings should remain queryable in PostgreSQL via pgvector unless scale clearly justifies a dedicated vector service.

---

## Eventing guidance

Each important transition should create an audit/event record, including:

- run created
- plan generated
- approval requested
- approval granted/rejected
- patch created
- patch approved/rejected
- validation started/completed
- run completed/failed/cancelled
