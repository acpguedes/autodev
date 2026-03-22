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
- PostgreSQL and Redis-backed async execution remain pending in the next slices.

Success criteria:
- sessions survive restart
- runs can be resumed and inspected
- UI can query history and statuses

---

## Release 0.3 - Repository intelligence

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

