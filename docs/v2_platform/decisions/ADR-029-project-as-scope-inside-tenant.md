# ADR-029: Project as a Scope Inside a Tenant

- **Status:** Accepted
- **Date:** 2026-10-04
- **Authors:** AutoDev platform team
- **Related epic:** E62
- **Relates to:** ADR-010 (multi-tenancy slice), ADR-025 (shared SQL
  persistence contract), ADR-028 (layered configuration)

## Context

Before E62 the platform had one filesystem path, held process-wide
(`RepositorySettings.project_root`). Sessions, context and memory were scoped by
tenant only, so two projects served by one backend could not be isolated, and
switching projects meant rewriting global configuration. E62 makes the project a
first-class, durable entity. The open question is where it sits relative to the
tenant, which is already the security boundary and the PostgreSQL RLS axis
(E50).

## Decision

**`tenant_id` remains the security boundary. `project_id` is an isolation scope
*inside* a tenant — not a second security boundary and not a replacement for
one.**

- Every table E62 touches keeps its tenant-first key and its
  `<table>_tenant_isolation` RLS policy. `projects` is created with
  `FORCE ROW LEVEL SECURITY` through the shared `_apply_tenant_rls()` generator.
  `project_id` is an additive column (`sessions.project_id`,
  `code_chunks.project_id`), never a substitute for `tenant_id` in a policy.
- Project scoping is enforced by explicit predicates in the stores and the
  retrieval pipeline (lexical ranker, vector ranker and the final chunk fetch).
  It protects against accidental cross-project reads by a *trusted* tenant; it
  does not contain an untrusted tenant. Tenant RLS remains the enforcement
  mechanism for that.
- A project's filesystem root is an operator-supplied path. It is registered
  through an administrative operation (`project:write`) and thereafter resolved
  **server-side from the stored record** — `backend/projects/resolution.py` is
  the single resolver; no request parameter carries a root for path resolution.
- Resolution order for a request: the session's project → an explicit project id
  → the tenant's active project → the process-wide configured root (retained as
  the fallback for installations and requests with no project at all).
- Registering a directory is additive: initializing `.autodev/` creates only the
  missing `config.json`/`project.json` files and never modifies, deletes or
  reorders a pre-existing file, never edits `.gitignore`, and never starts a run.
  This is a tested invariant, not a convention.

## Consequences

- Migrations are append-only: `create_projects_table` (both dialects) adds
  `projects` and `sessions.project_id`, backfilling every tenant's existing
  sessions onto a `default` project rooted at the configured project root;
  `add_project_id_to_code_chunks` widens `code_chunks`' unique key to include
  `project_id` (a SQLite table rebuild, since a `UNIQUE` constraint cannot be
  altered) so two projects may index the same relative path.
- `code_chunks.project_id = ''` is the unscoped legacy namespace; retrieval with
  no resolvable project queries that namespace, never "all projects".
- The per-project configuration layer `.autodev/config.json` joins the ADR-028
  composition between the global layer and the project's own
  `autodev.config.json`.
- Known limit: the LLM/runtime environment applied by
  `RuntimeConfigService.apply_to_environment()` is still process-wide; E62
  isolates sessions, filesystem roots, memory, repository knowledge and the
  *composition* of configuration per project, not the process environment.
