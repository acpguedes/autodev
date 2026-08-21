# E50 — PostgreSQL Schema, Migrations, Tenancy and RLS

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E49 (persistence contract), E8-S1 (`tenant_id` + RLS pattern,
ADR-010), E48 (a runtime the migrations can actually run against)
**Enables:** E51-E55 — each store port needs its tables to exist in
PostgreSQL, versioned and tenant-isolated, before it can be written.
**Canonical source:** this document, from a direct read of the current tree
(`d07b746`): thirteen tables are created by `CREATE TABLE IF NOT EXISTS`
inside `_create_schema` methods, none of them registered in
`POSTGRES_STORE_MIGRATIONS`, and none tracked by `schema_version`.

## Context and problem

The State Store has a real migration system: `MigrationRunner`
(`backend/persistence/migrations/runner.py`) with an ordered, append-only
list per engine, a `schema_version` namespace table, reversible `Migration(up,
down)` entries, and `SchemaVersionMismatchError` protection (E34-S3).
Eleven core tables use it, with RLS policies generated for the tenant-scoped
subset.

Thirteen tables do not. They are created imperatively at store construction,
so they exist only where a store happens to run, only on SQLite, with no
recorded version, no down path, and no RLS. Their `tenant_id` columns are
enforced by application-level `WHERE` clauses alone — including `secrets`,
`run_leases`, and `pending_action_decisions`, three of the most
security-sensitive tables in the platform.

`plan_step_state` is worse than the other twelve: it has no `tenant_id`
column at all, and no relationship to the plan or session it describes.

## Evidence in code

All thirteen tables, their definition site, and their PostgreSQL status:

| Table | Defined at | In `POSTGRES_STORE_MIGRATIONS` |
| --- | --- | --- |
| `tenant_quota_policies` | `backend/quotas/store.py:78` | no |
| `tenant_usage_windows` | `backend/quotas/store.py:84` | no |
| `run_leases` | `backend/quotas/store.py:92` | no |
| `storage_reservations` | `backend/quotas/store.py:101` | no |
| `request_rate_buckets` | `backend/quotas/store.py:110` | no |
| `secrets` | `backend/secret_store/store.py:91` | no |
| `execution_policy_rules` | `backend/execution/policy.py:235` | no |
| `execution_dynamic_permissions` | `backend/execution/policy.py:247` | no |
| `execution_policy_decisions` | `backend/execution/policy.py:259` | no |
| `pending_action_decisions` | `backend/execution/policy.py:272` | no |
| `execution_environments` | `backend/environments/store.py:126` | no |
| `execution_environment_decisions` | `backend/environments/store.py:143` | no |
| `plan_step_state` | `backend/plans/step_state.py:159` | no |

Verified by grepping each name against
`backend/persistence/migrations/postgres_versions.py`: zero matches for all
thirteen.

The pattern to reuse (not reinvent):
- `backend/persistence/migrations/runner.py:125` — `self._param = "?" if
  engine == "sqlite" else "%s"`; `:141-158` the `schema_version(namespace,
  version)` table; `:197-200` index-in-list is the version number;
  `:202-238` `rollback_to()` / `run_down()`; `:12`
  `SchemaVersionMismatchError`.
- `backend/persistence/migrations/postgres_versions.py:8` — "never edit or
  reorder"; `:163-173` the RLS generator: `ENABLE` + **`FORCE ROW LEVEL
  SECURITY`** + `CREATE POLICY <t>_tenant_isolation USING (tenant_id =
  current_setting('app.tenant_id', true))`. `FORCE` is required because the
  application connects as the table owner (`:155-158`).
- `backend/persistence/tenancy.py:20-45` — `set_postgres_tenant()` via
  parameter-safe `set_config('app.tenant_id', %s, true)`.
- `backend/quotas/migrations.py:69-107` — `check_postgres_tenant_isolation`
  reads `relrowsecurity`/`relforcerowsecurity` from `pg_class`; `:31`
  `ADDITIONAL_TENANT_SCOPED_TABLES = ("flow_runs", "artifacts", "events")`.
  None of the thirteen is listed.

`plan_step_state` specifically:
- `backend/plans/step_state.py:159` — no `tenant_id` column.
- `backend/plans/step_state.py:114-133` — the docstring states the gap
  outright: a PostgreSQL URL "falls back to a dedicated SQLite file" because
  per-step approval state "does not require extending the PostgreSQL
  schema/migrations for this story".

## Objective

Create versioned, reversible PostgreSQL migrations for all thirteen tables,
with correct PostgreSQL types, `tenant_id NOT NULL`, tenant-first indexes,
and Row-Level Security — so that in `prod` every relational table the
platform needs is created exclusively by the migration runner.

## Key result

A `prod` database created from empty contains all thirteen tables with
`relrowsecurity` and `relforcerowsecurity` true, a `<t>_tenant_isolation`
policy each, and a recorded `schema_version`; and a two-tenant isolation test
proves neither can read the other's rows.

## Scope

- `up` and `down` migrations for all thirteen tables, appended to the
  existing PostgreSQL migration list without renumbering.
- PostgreSQL-appropriate types: `JSONB` where the SQLite column holds JSON
  text, `TIMESTAMPTZ` for timestamps, `BIGINT` for counters.
- Constraints, foreign keys, unique constraints, and indexes — with
  tenant-scoped indexes beginning with `tenant_id`.
- `tenant_id NOT NULL` on every one of the thirteen.
- `ENABLE` + `FORCE ROW LEVEL SECURITY` and a tenant-isolation policy each.
- `plan_step_state` redesign: add `tenant_id` and a foreign key to the plan
  or session it belongs to.
- Extending `backend/quotas/migrations.py`'s verifier to cover the new
  tables.
- Idempotency, and validation that an old → upgraded → reverted database
  stays consistent.

## Out of scope

- Rewriting the stores to *use* these tables — that is E51-E55. This epic
  creates schema; the tables are legitimately unread until their port lands.
- Data migration from an existing SQLite installation (E58).
- SQLite schema changes, except the `plan_step_state` redesign, which must
  land on both backends together to keep local parity.
- Pooling, timeouts, and RLS-on-connection-reuse safety (E60).

## Stories

### E50-S1 — Quota and secret tables

Subtasks:
- `E50-S1-T1`: migrations for `tenant_quota_policies`,
  `tenant_usage_windows`, `run_leases`, `storage_reservations`, and
  `request_rate_buckets`, mirroring the SQLite semantics at
  `backend/quotas/store.py:78-118` with PostgreSQL types.
- `E50-S1-T2`: migration for `secrets`
  (`backend/secret_store/store.py:91`), preserving the version/active-version
  constraints the store relies on and keeping the column a ciphertext
  container only.
- `E50-S1-T3`: `tenant_id NOT NULL`, tenant-first composite indexes, and the
  unique constraints these tables depend on for their upsert paths.

| Criterion | Detail |
| --- | --- |
| Functional | All six tables created by the migration runner on an empty database; `down` removes them cleanly |
| Non-functional | `JSONB`/`TIMESTAMPTZ` used where appropriate; indexes tenant-first; no renumbering of existing migrations |
| DoR (specific) | E48 merged (migrations can run); E49-S1 merged |
| DoD (specific) | Up/down applied and re-applied idempotently against a real PostgreSQL |
| Dependencies | E48, E49 |

### E50-S2 — Execution policy and environment tables

Subtasks:
- `E50-S2-T1`: migrations for `execution_policy_rules`,
  `execution_dynamic_permissions`, `execution_policy_decisions`, and
  `pending_action_decisions` (`backend/execution/policy.py:235-283`).
- `E50-S2-T2`: migrations for `execution_environments` and
  `execution_environment_decisions`
  (`backend/environments/store.py:126-155`).
- `E50-S2-T3`: indexes serving the queries these stores actually run —
  pending-decision lookup and expiry scans — so E53 and E54 are not forced to
  add indexes retroactively under load.

| Criterion | Detail |
| --- | --- |
| Functional | All six tables created by the migration runner; `down` removes them cleanly |
| Non-functional | Pending/expiry query paths have supporting indexes; foreign keys expressed where the SQLite schema implied them |
| DoR (specific) | E50-S1 merged |
| DoD (specific) | Up/down applied idempotently; index presence asserted |
| Dependencies | E50-S1 |

### E50-S3 — `plan_step_state` redesign

Subtasks:
- `E50-S3-T1`: add `tenant_id NOT NULL` to `plan_step_state`, which has no
  tenant column today (`backend/plans/step_state.py:159`).
- `E50-S3-T2`: add the missing relationship — a foreign key to the plan or
  session the step belongs to — so step state cannot outlive or detach from
  its parent.
- `E50-S3-T3`: land the equivalent change on the SQLite migration list so
  local-first keeps parity, and define the backfill rule for existing rows
  that have no tenant (they map to `DEFAULT_TENANT_ID`, consistent with
  `backend/persistence/tenancy.py:17`).

| Criterion | Detail |
| --- | --- |
| Functional | Table exists on both backends with `tenant_id` and a parent foreign key; existing local rows backfill to the default tenant |
| Non-functional | The state-machine column semantics are unchanged by the schema move; SQLite parity preserved |
| DoR (specific) | E50-S2 merged; the parent entity (plan vs session) chosen and recorded |
| DoD (specific) | Up/down on both backends; backfill test from a pre-migration database |
| Dependencies | E50-S2, E16-S2 |

### E50-S4 — Row-Level Security and isolation proof

Subtasks:
- `E50-S4-T1`: apply `ENABLE` + `FORCE ROW LEVEL SECURITY` and a
  `<t>_tenant_isolation` policy to all thirteen tables, reusing the generator
  pattern at `postgres_versions.py:163-173` rather than writing new policy
  SQL per table.
- `E50-S4-T2`: extend `backend/quotas/migrations.py` — add the thirteen to
  the verifier's scope so `--check` reports on them alongside
  `ADDITIONAL_TENANT_SCOPED_TABLES`.
- `E50-S4-T3`: two-tenant isolation tests per table, and an
  old → upgrade → revert → re-upgrade consistency test proving the down
  migrations are real and not decorative.

| Criterion | Detail |
| --- | --- |
| Functional | With `app.tenant_id` set to tenant A, no query returns a tenant B row from any of the thirteen tables |
| Non-functional | `relrowsecurity` and `relforcerowsecurity` true for all thirteen, asserted programmatically via `pg_class` |
| DoR (specific) | E50-S1, E50-S2, E50-S3 merged |
| DoD (specific) | Isolation test per table; migration round-trip test green |
| Dependencies | E50-S1, E50-S2, E50-S3, E8-S1 |

## Contracts and decisions

### Architectural decisions required

- No new ADR. This epic applies decisions already recorded: ADR-010
  (`tenant_id` + RLS as the isolation mechanism, with down-migration support)
  and ADR-001. If E50-S3 chooses a parent entity for `plan_step_state` that
  changes a public contract, that is recorded in the E55 epic, not here.

### Security and multitenancy

- This epic is where the platform's largest isolation gap closes: `secrets`,
  `run_leases`, and `pending_action_decisions` currently rely on application
  `WHERE` clauses alone.
- `FORCE ROW LEVEL SECURITY` is mandatory, not optional — the application
  connects as the table owner, and plain `ENABLE` does not restrict an owner
  (`postgres_versions.py:155-158`).
- Policies must read `current_setting('app.tenant_id', true)`; the
  three-argument `set_config` form stays the only way the value is set.
- Creating RLS on a table before its store is ported (E51-E55) is deliberate:
  the isolation guarantee is in place from the first write.

### Migration strategy

- Append-only. Existing PostgreSQL migrations 1-7 are never edited or
  renumbered (`postgres_versions.py:8`).
- Every new migration has a real `down`, validated by the round-trip test in
  E50-S4-T3.
- Idempotent: re-running the runner against an already-migrated database is a
  no-op.
- `SchemaVersionMismatchError` behavior is preserved — a database migrated by
  newer code still refuses older code.

### Compatibility and rollback

- SQLite is unchanged except for `plan_step_state` (E50-S3), which lands on
  both backends together.
- Rollback is `rollback_to()` on the pre-epic version; because the stores do
  not yet read these tables (E51-E55 not yet landed), rolling back this epic
  cannot lose live production data.

## Testing and observability

Tests required:
- Up and down for each migration, against a real PostgreSQL (CI in E57).
- Idempotent re-run.
- Two-tenant isolation per table.
- `pg_class` assertion of `relrowsecurity`/`relforcerowsecurity`.
- Old → upgraded → reverted → re-upgraded consistency.
- `plan_step_state` backfill from a pre-migration database, both backends.

Observability:
- `autodev doctor` / the tenancy verifier reports RLS coverage for the
  thirteen tables (E50-S4-T2), so a misconfigured deployment is detectable
  without reading `pg_class` by hand.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Type drift between SQLite text-JSON and PostgreSQL `JSONB` | Values read back with different shapes | Shared codecs own decoding (E49-S2-T3); contract tests compare shapes across backends (E56) |
| A `down` migration is written but never exercised | Rollback fails when it is actually needed | E50-S4-T3 makes the round trip a required test |
| RLS applied but the tenant GUC never set by a caller | Queries silently return nothing, read as "no data" | Tenant application lives in the contract (E49-S1-T3); isolation tests assert both directions |
| `plan_step_state` parent FK chosen wrongly | Rework in E55 | Decide the parent entity in DoR before writing the migration (E50-S3 DoR) |
| Tables exist unused between E50 and E51-E55 | Confusing intermediate state | Stated explicitly here as intended; E57's CI asserts schema, not usage, until the ports land |

## DoR / DoD

- **DoR:** E48 merged (a runtime that can run migrations); E49-S1 merged;
  the `plan_step_state` parent entity decided.
- **DoD:** all four story DoDs met; thirteen tables created only by
  migrations; RLS enforced and verified on all thirteen; up/down round trip
  green; `docs/v2_platform/progress.md` updated; no push or PR without
  explicit authorization.

## Exit evidence

1. `schema_version` contents after a from-empty migration, showing the new
   versions.
2. `pg_class` query output showing `relrowsecurity` and
   `relforcerowsecurity` true for all thirteen tables.
3. Two-tenant isolation test output.
4. Migration round-trip (up → down → up) output.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`, `docs/feature_matrix.md` (the RLS
row, which today claims tenant isolation without qualifying which tables),
`docs/security.md`.

Code: `backend/persistence/migrations/postgres_versions.py`,
`backend/persistence/migrations/versions.py` (SQLite side of E50-S3),
`backend/quotas/migrations.py` (verifier scope),
`backend/plans/step_state.py` (schema definition only; the store port is
E55).
