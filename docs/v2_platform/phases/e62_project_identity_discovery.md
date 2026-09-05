# E62 — Project Identity, Discovery and Multi-Project Isolation

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E61).
**Status:** Not started · **Stories:** 0/5
**Depends on:** E61-S1/S2 (global home and layered configuration — the project
layer needs a global layer to inherit from), E49 (shared SQL persistence
contract, mandatory for any new store), E50 (tenant RLS generator), E8-S1
(multi-tenant schema and `MigrationRunner`)
**Enables:** E63 (flow selection needs a resolved project whose real state can
be probed) and E65 (a terminal session must be bound to a project, not to a
process-wide path).
**Canonical source:** this document, plus direct inspection of
`backend/config/runtime.py`, `backend/api/routers/repository_files_v2.py` and
`backend/persistence/migrations/versions.py` (2026-09-05).

## Context and problem

The platform has no concept of a project. It has one filesystem path, held
process-wide.

`RepositorySettings.project_root` (`backend/config/runtime.py:37`) defaults to
`AUTODEV_PROJECT_ROOT` or `Path.cwd()`, is persisted in a single
`autodev.config.json`, and is read identically by every consumer:
`build_default_orchestrator()`, `get_project_root_v2()`,
`get_patch_workspace_root()`, `_resolve_within_project_root()`,
`sandbox_policy_from_settings()` and `backend/api/routers/mcp_v2.py`. The
codebase states the assumption explicitly rather than hiding it —
`backend/api/routers/repository_files_v2.py:9-13`:

> "The platform currently has one project root per deployment (every other
> `/v2` router ... resolves it the same way), **not one per session**, so there
> is no per-session root to look up here either."

Four consequences follow directly:

1. **No discovery.** There is no ancestor-directory search for a marker
   anywhere in `backend/` — no `.parents` iteration, no `while parent !=
   parent.parent`. Running the tool from a subdirectory of a project does not
   find that project; it makes the subdirectory the project.

2. **`.autodev/` is not a project marker.** It exists only as four unrelated
   relative output paths — `.autodev/backup-status.json`
   (`backend/config/settings.py:180`), `.autodev/upgrade-backups/<ts>`
   (`backend/cli.py:908`), `.autodev/execution-notes/<task>.md`
   (`backend/execution/executor.py:391`), and a plugin-permission documentation
   example. None is ever searched for.

3. **No project entity.** `backend/persistence/migrations/versions.py` creates
   eighteen tables; none is `projects`. `sessions` is
   `id, goal, plan_json, artifacts_json, created_at, updated_at` (+ `tenant_id`
   from `_m7`) — no project column. `grep "projects" backend/api/` returns zero
   hits. The only "project" in the domain model is `SecretReference.project`,
   a naming label inside a tenant with no link to a filesystem root.

4. **Switching projects means mutating global state.** `autodev config set
   --project-root` or `PUT /v2/config` rewrites the one document, for the whole
   process — so context and memory cannot be isolated per project, because
   there is nothing to isolate them by. Session memory is
   `SessionMemoryContextProvider` reading the `messages` table; repository
   knowledge is `code_chunks`/`code_embeddings`; both are scoped by tenant only.

Requirement 4.3 adds a behavior the current design cannot express at all: when
no configured project is found, offer to open an existing project, configure an
existing directory, or create a new one — and **configuring a directory must not
be confused with restructuring it**. Today the absence of configuration is
indistinguishable from the absence of a project, and there is no path that
initializes metadata without also making the directory the implicit project.

## Evidence in code and documentation

- `backend/config/runtime.py:37` — `project_root` default; `:161-179` —
  `_env_or_cwd_project_root` / `_resolve_config_path`.
- `backend/api/routers/repository_files_v2.py:9-13` — the single-root
  assumption, stated in the module docstring; `:38-46` — `get_project_root_v2`.
- `backend/api/routers/patches_review_v2.py:181` — `get_patch_workspace_root`.
- `backend/api/routers/repo_symbols.py:27` — `_resolve_within_project_root`,
  which mirrors `backend/patches/engine.py::apply_patch`'s containment guard.
- `backend/orchestrator/service/message_job.py:25-42` —
  `build_default_orchestrator()`, the **single** construction point used both by
  every `/v2` router (via `sessions_v2.get_orchestrator_v2`) and by the
  background message-run job.
- `backend/validation/sandbox.py:92` — `sandbox_policy_from_settings` reading
  `settings.autodev_project_root` with a `"."` fallback.
- `backend/persistence/migrations/versions.py:40-47` — the `sessions` table;
  `_m7_add_tenant_id_to_core_tables` — the additive-column-with-backfill
  pattern this epic reuses.
- `backend/persistence/migrations/postgres_versions.py:966` —
  `POSTGRES_STORE_MIGRATIONS`; `E50_TENANT_SCOPED_TABLES` and
  `_apply_tenant_rls()` — the RLS generator every tenant-scoped table uses.
- `backend/persistence/contract.py` (E49, ADR-025) — the mandatory persistence
  boundary; an automated guard blocks a domain module from opening a connection
  directly.
- `backend/context/providers/session_memory.py` — the only memory implementation.

## Objective

Make a project a first-class, discoverable, durable entity: found by walking up
from the working directory, described by files inside the project, persisted so
that sessions, context and memory belong to one project, and creatable through
three explicit paths that never restructure what is already there.

## Key result

Running `autodev` in any subdirectory of a configured project finds that
project; two projects served by the same backend do not see each other's
sessions, context or memory; and configuring `.autodev/` in an existing
directory changes nothing else about that directory.

## Scope

- Ancestor-walking discovery of `.autodev/`, nearest occurrence wins.
- Typed schemas for `.autodev/config.json` and `.autodev/project.json`,
  with Git optional.
- A `projects` table on both dialects with tenant RLS, and a store on the E49
  contract.
- `sessions.project_id`, backfilled.
- Per-session/per-request project root resolution replacing the process-wide
  path at its six consumers.
- `/v2/projects` plus the CLI and UI surfaces for the three no-project paths.
- Proof that sessions, messages and repository knowledge are isolated per
  project.

## Out of scope

- Multi-repository search scope within one project (`repo_ids: list[str]`,
  reference §11.7) — a different axis, roadmap-level.
- Moving repository knowledge out of the shared database onto per-project disk
  storage; scoping the existing tables by project is what isolation requires.
- Any change to tenant semantics. Project is a scope *inside* a tenant, never a
  replacement for one.
- Project templates or scaffolding content — deliberately, because E62-S4's
  whole point is that configuring a project is not scaffolding it.

## Stories

### E62-S1 — Project discovery and on-disk metadata

Subtasks:
- `E62-S1-T1`: a new `backend/projects/discovery.py` that walks from a starting
  directory up through its ancestors looking for `.autodev/`, returning the
  **nearest** match as the project root, and `None` when there is none.
  Terminates at the filesystem root; does not cross into a parent that the
  caller has no permission to read.
- `E62-S1-T2`: typed models for `.autodev/config.json` — which may legitimately
  be `{}` — and `.autodev/project.json`, carrying the project name and Git
  information when a repository is present. **A project without Git is a
  project**; Git information is recorded when available and its absence is never
  an error.
- `E62-S1-T3`: an invalid file raises `ProjectConfigError` naming the file path
  and the specific problem, and is never degraded into "no project found" —
  the same fail-loudly posture E61-S2-T3 establishes for the configuration
  layers.

| Criterion | Detail |
| --- | --- |
| Functional | A project is found from any depth of subdirectory; the nearest `.autodev/` wins over an outer one; a Git-less directory is recognized |
| Non-functional | Discovery is pure path traversal — no network, no database, no LLM |
| DoR (specific) | E61-S1 merged |
| DoD (specific) | Tests for: found at depth; nested projects resolve to the nearest; no marker returns `None`; malformed `config.json` and `project.json` each raise with their own path in the message |
| Dependencies | E61-S1 |

### E62-S2 — `projects` as a durable entity

Subtasks:
- `E62-S2-T1`: append a `projects` migration to **both** lists — `STORE_MIGRATIONS`
  (`backend/persistence/migrations/versions.py`) and `POSTGRES_STORE_MIGRATIONS`
  (`postgres_versions.py`) — with the PostgreSQL types and tenant-first keys
  E50 established, and register the table with `_apply_tenant_rls()` /
  `E50_TENANT_SCOPED_TABLES` so it is `FORCE ROW LEVEL SECURITY` like the other
  thirteen.
- `E62-S2-T2`: a `ProjectStore` on the E49 contract
  (`backend/persistence/contract.py`) — obtaining its connection from the
  configured State Store, never opening `sqlite3` or resolving `DATABASE_URL`
  itself, because the automated boundary guard blocks that outright.
- `E62-S2-T3`: add `project_id` to `sessions` on both dialects, backfilled to a
  default project derived from the currently configured `project_root`, using the
  additive-column-with-backfill shape `_m7_add_tenant_id_to_core_tables` already
  proved. An existing installation must come up with every session attached to a
  real project, not to `NULL`.

| Criterion | Detail |
| --- | --- |
| Functional | Projects persist per tenant on SQLite and PostgreSQL; every pre-existing session is attached to a project after migration |
| Non-functional | RLS forced on PostgreSQL; the store passes the E49 contract suite; no direct connection |
| DoR (specific) | E62-S1 merged |
| DoD (specific) | Migration applies from empty and is idempotent on re-run; cross-tenant read returns zero rows on PostgreSQL; backfill test on a database seeded with pre-migration sessions |
| Dependencies | E49, E50, E62-S1 |

### E62-S3 — Per-session project root resolution

Subtasks:
- `E62-S3-T1`: resolve the project root from the session's project at each of
  the six consumers — `build_default_orchestrator()`
  (`backend/orchestrator/service/message_job.py:38`, the single construction
  point, which makes this a small change rather than a sweep),
  `get_project_root_v2()`, `get_patch_workspace_root()`,
  `_resolve_within_project_root()`, `sandbox_policy_from_settings()` and
  `backend/api/routers/mcp_v2.py` — falling back to the active project when a
  request carries no session.
- `E62-S3-T2`: correct the now-false single-root statement in
  `backend/api/routers/repository_files_v2.py`'s module docstring rather than
  leaving documentation that contradicts the code.
- `E62-S3-T3`: the path-containment guard is unchanged in *kind* — still
  `backend/patches/engine.py::apply_patch`'s `resolve()` + `relative_to()` check
  — but is now evaluated against the session's project root, so a session cannot
  read or write outside its own project even when another project exists on the
  same host.

| Criterion | Detail |
| --- | --- |
| Functional | Two sessions bound to different projects resolve different roots in the same process |
| Non-functional | No new resolution mechanism; the same containment guard, evaluated per session |
| DoR (specific) | E62-S2 merged |
| DoD (specific) | A test that a session bound to project A cannot read a file in project B, using the existing traversal-guard test as its model |
| Dependencies | E62-S2 |

### E62-S4 — `/v2/projects` and the three no-project paths

Subtasks:
- `E62-S4-T1`: `/v2/projects` — list, and the three creation paths as distinct
  operations: **open** an existing project (validate its `.autodev/` and
  activate it), **initialize** an existing directory (create `.autodev/` and its
  metadata, preserving every file already present), and **create** a project
  (make the directory, then initialize it).
- `E62-S4-T2`: mirror the three paths in the CLI (`autodev project
  list|open|init|create`), which is where a user who has no UI yet actually
  starts.
- `E62-S4-T3`: the frontend surfaces them: an onboarding view when no project is
  active, and a project selector in `ContextHeader` replacing the free-text
  `project_root` field in `frontend/app/config/page.tsx`.
- `E62-S4-T4`: the invariant that gives this story its reason to exist —
  **initializing `.autodev/` in an existing directory does not trigger a
  structuring flow and does not modify or delete any pre-existing file.**
  Asserted as a test, not stated as a convention.

| Criterion | Detail |
| --- | --- |
| Functional | All three paths work from the API, the CLI and the UI; the absence of `.autodev/` presents a choice rather than an assumption |
| Non-functional | Initialization is additive only; a directory's existing contents are byte-identical afterwards |
| DoR (specific) | E62-S3 merged |
| DoD (specific) | A test that initializes a directory containing files and asserts no file changed and no flow run was started |
| Dependencies | E62-S3 |

### E62-S5 — Isolation proof

Subtasks:
- `E62-S5-T1`: scope session memory by project —
  `SessionMemoryContextProvider` reads `messages` through a session that now
  belongs to a project, so the isolation must be asserted end to end rather than
  assumed from the schema.
- `E62-S5-T2`: scope repository knowledge by project: `code_chunks` and
  `code_embeddings` are tenant-scoped today, so two projects in one tenant share
  an index. Add the project scope to indexing and retrieval, and prove a query in
  project A never returns a chunk from project B.
- `E62-S5-T3`: prove the negative for configuration too — a project's
  `.autodev/config.json` does not leak into another project's resolution, which
  is the composition rule E61-S2 defines, verified here across two real projects.

| Criterion | Detail |
| --- | --- |
| Functional | Sessions, messages, retrieved context and configuration are isolated per project within one tenant |
| Non-functional | Isolation asserted by test, in the E51-E55 tradition of proving the invariant rather than describing it |
| DoR (specific) | E62-S4 merged |
| DoD (specific) | A two-project test covering all three axes |
| Dependencies | E62-S4 |

## Contracts and decisions

### Architectural decisions required

- A new ADR is required: **project as a scope inside a tenant**. It fixes that
  `tenant_id` remains the security boundary and RLS axis, while `project_id` is
  an isolation scope *within* a tenant — not a second security boundary, and not
  a replacement for one. Every table this epic touches keeps its tenant-first
  key and its tenant RLS policy; the project column is additive.
- `/v2/projects` is a new API surface and therefore additive under §19.1;
  `schemaVersion` conventions apply as for every other `/v2` payload.

### Security and multitenancy

- `projects` carries `FORCE ROW LEVEL SECURITY` and a `<t>_tenant_isolation`
  policy from the shared `_apply_tenant_rls()` generator, exactly like the
  thirteen tables E50-S4 covered.
- Every lookup takes an explicit `tenant_id` to scope the `app.tenant_id` GUC —
  E51-E55 proved that an unscoped connection reads zero rows under forced RLS,
  so this is a correctness requirement, not defense in depth.
- Project roots are operator-supplied filesystem paths. The API must never
  accept a project root from an untrusted client for path resolution; it
  resolves the root server-side from the stored project record.

### Migration strategy

- Two appended migrations (SQLite and PostgreSQL), never edited or reordered,
  per the header rule in `postgres_versions.py`.
- `sessions.project_id` is backfilled to a default project derived from the
  configured `project_root`, so no row is left unattached.
- `MigrationRunner.run_pending()` continues to refuse a database whose recorded
  schema version is newer than the installed code knows (E34-S3).

### Compatibility and rollback

- A single-project installation behaves identically: discovery finds one
  project, every session attaches to it, and no user-visible behavior changes
  except that the project is now named.
- Rollback is the migrations' `down` steps plus reverting the resolution change;
  the process-wide fallback path is retained for a request that carries no
  session.

## Testing and observability

Tests required:
- Discovery: at depth, nested, absent, and each malformed-file case.
- Migration from empty, idempotent re-run, and backfill over pre-existing rows.
- Cross-tenant RLS on `projects` (PostgreSQL).
- Two sessions in one process resolving different roots.
- A session bound to project A refused a file in project B.
- Initialize-in-place changes no file and starts no run.
- Two-project isolation of sessions, retrieval and configuration.

Observability:
- `autodev doctor` reports the discovered project root and how it was found
  (marker at depth *n*, or none), through the existing typed-check structure in
  `backend/ops/doctor.py`.
- Project creation and activation emit catalog events following the
  `domain.entity.action` past-tense convention, appended to `EVENT_CATALOG`.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Backfill attaches sessions to the wrong project | Historical sessions appear under a project they did not belong to | Backfill derives from the configured `project_root` — the only project that existed — and is asserted on a seeded pre-migration database |
| Per-session resolution missed at one consumer | One code path still uses the process-wide root, silently crossing projects | The six consumers are enumerated in E62-S3-T1 and covered by the cross-project refusal test |
| Project treated as a security boundary it is not | False confidence that project scoping contains an untrusted tenant | The ADR states the boundary explicitly; tenant RLS remains the enforcement mechanism |
| Initializing a directory perceived as restructuring it | The exact defect this program exists to fix, reappearing in the onboarding path | E62-S4-T4 is a tested invariant covering both file contents and run creation |
| Repository index rebuilt per project inflates storage | Larger `code_chunks` for a multi-project host | Scoping is a column and a filter, not a duplicate index; retention behavior is unchanged |

## DoR / DoD

- **DoR:** E61-S1/S2 merged; the project-as-scope ADR written and Accepted.
- **DoD:** all five story DoDs met; discovery from a subdirectory proven;
  `projects` migrated on both dialects with RLS; every session attached to a
  project; the six consumers resolving per session; the three no-project paths
  working with the additive-only invariant tested; two-project isolation proven;
  `docs/v2_platform/progress.md` updated.

## Affected documents and code

Documents: `docs/execution/paths-and-config.md`, a new
`docs/projects/discovery.md`, a new ADR under `decisions/`,
`docs/v2_platform/progress.md`, `CHANGELOG.md`, `README.md`.

Code: `backend/projects/` (new: `discovery.py`, `models.py`, `store.py`),
`backend/api/routers/projects_v2.py` (new),
`backend/persistence/migrations/versions.py`,
`backend/persistence/migrations/postgres_versions.py`,
`backend/api/routers/sessions_v2.py`,
`backend/api/routers/repository_files_v2.py`,
`backend/api/routers/patches_review_v2.py`,
`backend/api/routers/repo_symbols.py`, `backend/api/routers/mcp_v2.py`,
`backend/orchestrator/service/message_job.py`, `backend/validation/sandbox.py`,
`backend/repository/indexing.py`, `backend/context/providers/session_memory.py`,
`backend/cli.py`, `backend/events/catalog.py`,
`frontend/components/shell/ContextHeader.tsx`, `frontend/app/config/page.tsx`.
