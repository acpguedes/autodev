# E53 — PolicyStore on PostgreSQL

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/3
**Depends on:** E49 (persistence contract), E50-S2 (execution-policy
migrations), E14 / ADR-022 / RFC-010 (execution policy engine and contract)
**Enables:** the execution policy engine, dynamic permissions, decision
auditing, and human-in-the-loop approvals to function in the `prod` profile
across multiple replicas.
**Canonical source:** this document, from a direct read of the current tree
(`d07b746`): `PolicyStore` raises `ValueError` on the `postgresql://` URL the
`prod` profile mandates, so governed execution — the mechanism that decides
what an agent is allowed to do — cannot start in production.

## Context and problem

`PolicyStore` owns four tables covering the whole execution-governance
surface: static rules, dynamically granted permissions, an audit trail of
decisions, and the queue of pending human decisions. All four are SQLite-only
and unversioned, and the store refuses a PostgreSQL URL
(`backend/execution/policy.py:206`).

The pending-decision path is the sharpest correctness risk. A pending action
must reach a terminal state exactly once: approving and rejecting the same
action, or approving it twice, are both governance failures. Today the
transition is a plain SQLite update with no explicit locking — no
`BEGIN IMMEDIATE`, unlike `QuotaStore` and `SecretStore`. On a single-process
SQLite deployment the database's own write serialization hides this. On
PostgreSQL with multiple replicas, nothing would.

## Evidence in code

- `backend/execution/policy.py:198-207` — private `_resolve_db_path`; `:206`
  raises `ValueError("PolicyStore requires a sqlite:// DATABASE_URL")`.
- `backend/execution/policy.py:227` — `sqlite3.connect(...)`.
- `backend/execution/policy.py:235, 247, 259, 272` — `execution_policy_rules`,
  `execution_dynamic_permissions`, `execution_policy_decisions`, and
  `pending_action_decisions` created by `CREATE TABLE IF NOT EXISTS`, outside
  `MigrationRunner`.
- `backend/execution/policy.py:298-530` — `?` placeholders and `sqlite3.Row`
  throughout; **no `BEGIN IMMEDIATE` anywhere**, so terminal transitions rely
  on SQLite's implicit write serialization.
- `backend/execution/policy.py:565` — `self._store = store or PolicyStore()`.
- `backend/execution/decisions.py:65` — `self._store = store or
  PolicyStore()`, the second construction site.
- `backend/cli.py:235-249` — `permissions list|revoke` are operator-facing
  commands over this store.
- `backend/persistence/migrations/postgres_versions.py` — none of the four
  tables present.

## Objective

Port `PolicyStore` to both backends through the E49 contract, with terminal
decision transitions that are atomic and idempotent across replicas, and with
the indexes the pending and expiry queries require.

## Key result

A pending decision reaches a terminal state exactly once even when approval
and rejection arrive concurrently from different replicas; the loser observes
the decided outcome rather than overwriting it.

## Scope

- Execution policy rules and dynamic permissions on both backends.
- Decision audit records.
- Pending human decisions, including atomic terminal transition.
- Expiry of pending decisions and of dynamic permissions.
- Idempotent resolution.
- Indexes for pending and expired decision queries.
- Fail-closed behavior in production.
- Multitenant isolation.

## Out of scope

- Changing policy semantics or the decision contract — ADR-022 and RFC-010
  stand; this is a persistence port.
- The four migrations themselves (E50-S2).
- Environment decisions (`execution_environment_decisions`), which belong to
  `EnvironmentStore` and E54.
- Pooling and timeouts (E60).

## Stories

### E53-S1 — Rules and dynamic permissions

Subtasks:
- `E53-S1-T1`: move `PolicyStore` onto the E49 contract — remove
  `sqlite3.connect`, the private `_resolve_db_path`, the PostgreSQL rejection
  guard, and `_create_schema`.
- `E53-S1-T2`: port `execution_policy_rules` read/write, keeping rule
  evaluation order and precedence observably unchanged.
- `E53-S1-T3`: port `execution_dynamic_permissions`, including grant, revoke,
  and expiry-aware lookup.

| Criterion | Detail |
| --- | --- |
| Functional | Rule evaluation and permission grant/revoke behave identically on both backends; `prod` can construct `PolicyStore` |
| Non-functional | No `sqlite3` import remains in `backend/execution/policy.py`; both construction sites work unchanged |
| DoR (specific) | E49-S2 and E50-S2 merged |
| DoD (specific) | Existing policy and permission tests green on both backends |
| Dependencies | E49, E50-S2 |

### E53-S2 — Decision audit and atomic terminal transition

Subtasks:
- `E53-S2-T1`: port `execution_policy_decisions` as an append-only audit
  trail, preserving its ordering guarantees.
- `E53-S2-T2`: make the `pending_action_decisions` terminal transition atomic
  — a conditional update guarded on the current pending state, so exactly one
  concurrent caller wins and the others observe the decided outcome.
- `E53-S2-T3`: make resolution idempotent — replaying the same decision with
  the same identity returns the recorded outcome instead of erroring or
  double-recording.

| Criterion | Detail |
| --- | --- |
| Functional | A pending decision reaches a terminal state exactly once; concurrent approve/reject yields one recorded outcome |
| Non-functional | Atomicity comes from a conditional update, not from caller-side checking |
| DoR (specific) | E53-S1 merged |
| DoD (specific) | Concurrency test: simultaneous approve and reject leave exactly one terminal state |
| Dependencies | E53-S1 |

### E53-S3 — Expiry, indexes and fail-closed

Subtasks:
- `E53-S3-T1`: expiry for pending decisions and dynamic permissions,
  reclaimed exactly once and never resurrecting an expired grant.
- `E53-S3-T2`: verify the E50-S2-T3 indexes actually serve the pending and
  expired query paths, and add any that measurement shows missing.
- `E53-S3-T3`: fail-closed behavior — when the store is unreachable, policy
  evaluation must deny rather than permit, and tenant isolation tests must
  cover all four tables.

| Criterion | Detail |
| --- | --- |
| Functional | Expired decisions and permissions stop granting access; unavailability denies |
| Non-functional | Pending and expiry queries use an index, verified rather than assumed |
| DoR (specific) | E53-S2 merged; E50-S4 RLS applied to the four tables |
| DoD (specific) | Expiry, fail-closed, and isolation tests green; query plans confirm index use |
| Dependencies | E53-S2, E50-S4 |

## Contracts and decisions

### Architectural decisions required

- No new ADR. ADR-022 (execution policy engine) and RFC-010 (execution policy
  contract) define the semantics being preserved. A change in decision
  semantics forced by the port would require an amendment referencing
  ADR-022, and is not expected.

### Security and multitenancy

- Fail-closed is the governing property: a policy store that cannot be read
  must deny. Permitting on error would turn a database outage into an
  authorization bypass.
- Double-approval is a governance failure with audit consequences — the audit
  trail must show one decision, not a race.
- All four tables are RLS-protected by E50-S4; a dynamic permission granted
  in one tenant must be invisible in another.
- The audit trail stays append-only; the port must not introduce an update
  path over decision history.

### Migration strategy

- No schema work here (E50-S2).
- `_create_schema` is removed; table existence becomes the migration runner's
  responsibility, bringing the four tables under `schema_version` for the
  first time.

### Compatibility and rollback

- SQLite local-first behavior preserved, including the current single-process
  guarantees.
- Existing SQLite policy data is untouched; moving it is E58.
- Rollback is reverting the port; the PostgreSQL tables created by E50 remain
  present and unused.

## Testing and observability

Tests required:
- Existing policy, permission, and decision suites, green on both backends.
- Concurrent approve/reject leaving exactly one terminal state.
- Idempotent replay of a decision.
- Expiry of pending decisions and dynamic permissions.
- Fail-closed on backend unavailability.
- Tenant isolation on all four tables.
- Query-plan verification for the pending and expiry paths.

Observability:
- Existing execution-policy events and access-audit records must keep
  working; decision outcomes remain traceable to their run.
- Pending-decision queue depth is a useful readiness signal but belongs with
  E60-S4's metric work rather than being added ad hoc here.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Terminal transition remains a plain update after the port | Double approval across replicas | E53-S2-T2 makes it a state-guarded conditional update; concurrency test is a DoD gate |
| Fail-open on store unavailability | Authorization bypass during an outage | E53-S3-T3 asserts denial explicitly |
| Missing index on the pending-decision query | Table scans on the human-approval hot path | E50-S2-T3 creates them; E53-S3-T2 verifies with real query plans |
| Expired permission still granting access | Privilege persists past its window | Expiry-aware lookup in E53-S1-T3, plus expiry tests in E53-S3-T1 |
| Two construction sites drift | One path ported, one not | Both `policy.py:565` and `decisions.py:65` covered in E53-S1 DoD |

## DoR / DoD

- **DoR:** E49-S2 and E50-S2 merged; a real PostgreSQL available to the test
  suite.
- **DoD:** all three story DoDs met; `prod` constructs and uses `PolicyStore`
  on PostgreSQL from both construction sites; exactly-once terminal
  transition proven under concurrency; fail-closed proven;
  `docs/v2_platform/progress.md` updated; no push or PR without explicit
  authorization.

## Exit evidence

1. Concurrency test output: simultaneous approve and reject producing one
   terminal state and one audit record.
2. Idempotent replay returning the recorded outcome.
3. Fail-closed output showing denial when the store is unreachable.
4. Query plans for the pending and expired decision queries showing index
   use.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`, `docs/feature_matrix.md`
(execution-policy rows), `docs/security.md`,
`docs/v2_platform/beta_acceptance_flow.md` (negative path N1, permission
denied).

Code: `backend/execution/policy.py`, `backend/execution/decisions.py`,
`backend/cli.py` (only if command behavior changes).
