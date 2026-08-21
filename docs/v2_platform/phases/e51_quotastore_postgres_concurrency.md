# E51 — QuotaStore on PostgreSQL and Concurrency

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E49 (persistence contract, row-lock primitive), E50-S1
(quota table migrations), E11-S3 / ADR-019 (quota and run-budget semantics)
**Enables:** quota enforcement, run leases, storage reservations, and rate
limiting to function at all in the `prod` profile, and to remain correct
across multiple API replicas rather than within one process.
**Canonical source:** this document, from a direct read of the current tree
(`d07b746`): `QuotaStore` raises `ValueError` on a `postgresql://` URL, which
the `prod` profile mandates — so quota enforcement is not degraded in
production, it is unreachable.

## Context and problem

`backend/config/settings.py:332-336` requires `DATABASE_URL` to start with
`postgresql://` or `postgres://` when `AUTODEV_PROFILE=prod`.
`backend/quotas/store.py:49` raises `ValueError` for exactly those URLs.
`backend/quotas/service.py:87` constructs `QuotaStore()` with no injection
point. The three facts together mean the quota subsystem cannot be
instantiated in a valid production configuration.

Beyond reachability, the concurrency model does not survive the move.
`QuotaStore` serializes with SQLite's `BEGIN IMMEDIATE`, a whole-database
write lock. PostgreSQL has no equivalent, and translating `BEGIN IMMEDIATE`
to a bare `BEGIN` would silently drop the mutual exclusion that prevents
quota oversubscription and duplicate leases. The store's own docstring
already claims the correct PostgreSQL design — and that design does not
exist.

## Evidence in code

- `backend/quotas/store.py:41-51` — private `_resolve_db_path`; `:49` raises
  `ValueError("QuotaStore requires a sqlite:// DATABASE_URL. Got: ...")`.
- `backend/quotas/store.py:70` — `sqlite3.connect(str(self._db_path),
  timeout=30)`.
- `backend/quotas/store.py:78-118` — `_create_schema` creates all five tables
  with `CREATE TABLE IF NOT EXISTS`, outside `MigrationRunner`.
- `backend/quotas/store.py:166, 218, 310, 389, 435` — `BEGIN IMMEDIATE`.
- `backend/quotas/store.py:391, 437` — `INSERT OR IGNORE`, SQLite-specific
  upsert syntax.
- **`backend/quotas/store.py:6-8`** — the docstring states PostgreSQL
  "serializes with `SELECT ... FOR UPDATE` inside an explicit transaction".
  `FOR UPDATE` appears nowhere in the repository. The docstring documents an
  unimplemented design and must be corrected, not preserved.
- `backend/quotas/service.py:87` — `self._store = store or QuotaStore()`.
- `backend/config/settings.py:332-336` — the `prod` requirement that makes
  the guard unreachable-by-construction.

## Objective

Port `QuotaStore` to run on both backends through the E49 contract, with
PostgreSQL concurrency semantics that genuinely prevent oversubscription,
double-commit, and duplicate leases across processes — not a mechanical
`?` → `%s` substitution.

## Key result

Under real concurrent load from multiple PostgreSQL connections, consumption
never exceeds the configured quota, no reservation or lease is duplicated,
and expired leases are reclaimed exactly once.

## Scope

- Quota policies and usage windows on both backends.
- Run leases: acquire, renew, expire, release.
- Storage reservations, including the commit path.
- Request rate buckets.
- Replacement of `BEGIN IMMEDIATE` with the E49 transaction/lock primitive.
- Correct PostgreSQL concurrency: `SELECT ... FOR UPDATE`, conditional
  updates, `ON CONFLICT`, `RETURNING`.
- Idempotency of each mutating operation.
- Concurrency tests using multiple real PostgreSQL connections.
- Correcting the false `FOR UPDATE` docstring claim.

## Out of scope

- Changing quota *policy semantics* (ADR-019 stands) — this is a persistence
  port, not a governance redesign.
- The quota table migrations themselves (E50-S1).
- Connection pooling (E60); this epic uses whatever E49 provides.
- The read-only tenancy verifier in `backend/quotas/migrations.py`, whose
  scope extension belongs to E50-S4-T2.

## Stories

### E51-S1 — Quota policies and usage windows

Subtasks:
- `E51-S1-T1`: move `QuotaStore` onto the E49 contract — remove
  `sqlite3.connect`, the private `_resolve_db_path`, and the PostgreSQL
  rejection guard; obtain the connection from the configured State Store.
- `E51-S1-T2`: port policy read/write (`tenant_quota_policies`) and usage
  windows (`tenant_usage_windows`), replacing `INSERT OR IGNORE` with the
  contract's upsert so both backends share one code path.
- `E51-S1-T3`: make usage accounting atomic — a conditional update that
  cannot overshoot, rather than read-then-write.

| Criterion | Detail |
| --- | --- |
| Functional | Policy get/set and usage accounting behave identically on both backends; `prod` can construct `QuotaStore` |
| Non-functional | No `sqlite3` import remains in `backend/quotas/store.py`; no dialect conditionals in method bodies |
| DoR (specific) | E49-S2 and E50-S1 merged |
| DoD (specific) | Existing quota unit tests green on both backends; an overshoot attempt is rejected |
| Dependencies | E49, E50-S1 |

### E51-S2 — Run leases

Subtasks:
- `E51-S2-T1`: port `run_leases` acquire/renew/release using row-level
  locking on PostgreSQL and the contract primitive on SQLite.
- `E51-S2-T2`: expired-lease reclamation that is safe under concurrency — an
  expired lease is reclaimed by exactly one caller, never two.
- `E51-S2-T3`: idempotent acquire — a retried acquire with the same identity
  returns the existing lease instead of creating a second.

| Criterion | Detail |
| --- | --- |
| Functional | Lease lifecycle correct on both backends; expiry reclaims exactly once |
| Non-functional | Concurrent acquire attempts for the same run produce one lease, verified with concurrent connections |
| DoR (specific) | E51-S1 merged |
| DoD (specific) | Concurrency test: N concurrent acquires yield exactly one holder |
| Dependencies | E51-S1 |

### E51-S3 — Storage reservations and rate buckets

Subtasks:
- `E51-S3-T1`: port `storage_reservations` including the reserve → commit
  transition, ensuring a reservation cannot be committed twice.
- `E51-S3-T2`: port `request_rate_buckets`, replacing the second
  `INSERT OR IGNORE` site with the contract upsert.
- `E51-S3-T3`: ensure reservation release and expiry cannot double-refund
  capacity.

| Criterion | Detail |
| --- | --- |
| Functional | Reserve/commit/release behave identically on both backends |
| Non-functional | Double-commit and double-refund are impossible by construction, not by caller discipline |
| DoR (specific) | E51-S1 merged |
| DoD (specific) | Tests for double-commit and double-refund attempts, both rejected |
| Dependencies | E51-S1 |

### E51-S4 — Concurrency proof and docstring correction

Subtasks:
- `E51-S4-T1`: multi-connection concurrency suite against a real PostgreSQL —
  concurrent consumption against a fixed quota, concurrent lease acquisition,
  concurrent reservation commit — asserting the invariants rather than
  timing.
- `E51-S4-T2`: cross-process/replica check, so the guarantee is shown to come
  from the database rather than from in-process state.
- `E51-S4-T3`: correct the docstring at `backend/quotas/store.py:6-8` to
  describe the implementation as it now exists.

| Criterion | Detail |
| --- | --- |
| Functional | Consumption never exceeds quota under concurrency; no duplicate leases or reservations |
| Non-functional | Tests assert invariants deterministically, not by sleeping; docstrings describe implemented behavior only |
| DoR (specific) | E51-S2 and E51-S3 merged |
| DoD (specific) | Concurrency suite green against a real PostgreSQL; docstring corrected |
| Dependencies | E51-S2, E51-S3, E57-S1 (real PostgreSQL in CI) |

## Contracts and decisions

### Architectural decisions required

- No new ADR. ADR-019 (multi-tenant quotas and run budgets) already defines
  the semantics; this epic makes them durable on PostgreSQL. If the port
  forces a semantic change — for instance to lease renewal under
  contention — that change is recorded as an amendment referencing ADR-019
  rather than silently implemented.

### Security and multitenancy

- All five tables are RLS-protected by E50-S4; every operation must go
  through the contract's tenant application so the `app.tenant_id` GUC is set
  inside the same transaction as the query.
- Quota bypass is a security property, not just a billing one: an
  oversubscription bug lets a tenant consume beyond its allocation.
- Lease identity must not be derivable across tenants.

### Migration strategy

- No schema work here; E50-S1 owns it.
- The store stops creating its own tables — `_create_schema` is removed, and
  table existence becomes the migration runner's responsibility.

### Compatibility and rollback

- SQLite behavior must remain observably identical for local-first users;
  the contract tests in E56 are the guarantee.
- Existing SQLite quota data is untouched by this epic; moving it to
  PostgreSQL is E58.
- Rollback is reverting the port; because E50 created the PostgreSQL tables
  independently, a revert leaves them empty and unused rather than broken.

## Testing and observability

Tests required:
- Existing quota unit tests, green on both backends.
- Atomic accounting: no overshoot.
- Lease lifecycle including expiry reclamation.
- Reservation reserve/commit/release, with double-commit and double-refund
  rejected.
- Multi-connection concurrency for all three invariants.
- Tenant isolation on all five tables.

Observability:
- Existing quota metrics and events must keep working after the port.
- Lock contention and deadlock metrics belong to E60-S4; this epic should not
  add ad-hoc counters.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| `BEGIN IMMEDIATE` translated to a bare `BEGIN` | Silent loss of mutual exclusion; quota oversubscription | E49-S2 provides an explicit lock primitive; E51-S4 asserts the invariant under real concurrency |
| Row locks taken in inconsistent order across operations | Deadlocks under load | Define and document a single lock ordering across the five tables; deadlock detection in E60-S3 |
| Long-held locks during quota checks | Throughput collapse | Keep critical sections minimal; `lock_timeout` lands in E60-S3 |
| Tests that pass by accident of timing | False confidence in concurrency safety | E51-S4-T1 asserts invariants, explicitly not timing |

## DoR / DoD

- **DoR:** E49-S2 and E50-S1 merged; a real PostgreSQL available to the test
  suite (E57-S1 for CI, local Compose meanwhile).
- **DoD:** all four story DoDs met; `prod` constructs and uses `QuotaStore`
  on PostgreSQL; concurrency invariants proven with real connections; the
  false docstring corrected; `docs/v2_platform/progress.md` updated; no push
  or PR without explicit authorization.

## Exit evidence

1. Concurrency suite output: N concurrent consumers against a fixed quota,
   with total consumption never exceeding it.
2. Concurrent lease acquisition output showing exactly one holder.
3. Double-commit and double-refund attempts rejected.
4. A `prod`-profile run exercising quota enforcement end to end.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`, `docs/feature_matrix.md`
(quota rows), `docs/config.md` if any quota-related variable changes meaning.

Code: `backend/quotas/store.py`, `backend/quotas/service.py`,
`backend/persistence/` (contract usage only).
