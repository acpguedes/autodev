# ADR-001 — PostgreSQL as Default Production State Store

- **Status:** Accepted
- **Date:** 2026-07-03
- **Epic:** E0
- **Stories:** E0-S3

## Context

AutoDev needs a durable production state store for sessions, runs, run steps,
messages, plan documents, and approvals. SQLite remains valuable for local-first
developer workflows, but production operation requires a networked database with
backup, restore, and future pgvector support.

## Decision

Use PostgreSQL as the default production state store and keep SQLite as the
local profile fallback. The repository factory selects the concrete store from
`DATABASE_URL`: `sqlite://` uses SQLite, while `postgres://` and
`postgresql://` use the PostgreSQL adapter.

## Consequences

- Production deployments must provide PostgreSQL and validated backup/restore
  procedures.
- Local E0 container workflows continue to boot with SQLite and the stub LLM
  provider.
- Future E8 persistence work can build on PostgreSQL for multi-tenant data,
  event stores, and pgvector.
