# E56 — SQLite/PostgreSQL Contract Test Suite

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Done · **Stories:** 3/3
**Depends on:** E49 (persistence contract), E50 (schema and RLS), E51-E55
(the ported stores that the contract must hold for)
**Enables:** the parity guarantee the platform's local-first promise rests
on, and the regression net that keeps a future change from working on one
backend only.
**Canonical source:** this document, plus the trade-off the reference
document already admits at §2.8: "Maintaining parity across backends doubles
the testing cost and creates a risk of divergence (a feature that only works
on Postgres)." Today that risk is unmanaged — every PostgreSQL path is tested
against fakes.

## Context and problem

The platform promises that moving from SQLite to PostgreSQL is "a
configuration change, not a code change" (reference §4.6). Nothing enforces
it. The PostgreSQL adapter's tests monkeypatch `sys.modules["psycopg"]`
(`backend/tests/unit/persistence/test_postgres_store.py:73-92`) and the
pgvector tests assert on recorded SQL strings
(`test_embeddings_pgvector.py:133-146`). Those tests verify that the code
*emits* the SQL its author intended; they cannot verify that PostgreSQL
accepts it, that it means the same thing as the SQLite statement, or that the
two backends return the same shapes.

That is how the current divergence became invisible. Five stores refuse
PostgreSQL outright and the suite stayed green, because no test ever asked a
store to behave identically on both backends.

E51-E55 each carry their own dual-backend tests. This epic turns those
scattered assertions into one reusable contract that every repository is held
to, so parity is a property of the codebase rather than a per-story habit.

## Evidence in code

- `backend/tests/unit/persistence/test_postgres_store.py:73-92` — PostgreSQL
  exercised through a monkeypatched `sys.modules["psycopg"]`.
- `backend/tests/unit/persistence/test_embeddings_pgvector.py:133-146` —
  assertions over recorded SQL strings rather than executed queries.
- `.github/workflows/ci-backend.yml:96-117` — `backend-tests` runs
  `pytest tests backend/tests` with no `services:` block; no PostgreSQL
  exists in CI (E57 adds it).
- `backend/sdk/testing.py:30` — the SDK test harness pins
  `sqlite:///{tmp}/contract.db` and uses `DurableStore`, which
  `backend/persistence/database.py:23` aliases unconditionally to
  `SQLiteStore`; the existing "contract" harness is therefore SQLite-only by
  construction.
- `backend/persistence/base.py` — the repository protocols that define what
  parity means.
- Skipping behavior: the PostgreSQL and MinIO backup/restore test variants
  auto-skip when the services are unavailable, so a green local run does not
  imply PostgreSQL coverage.

## Objective

Build one reusable contract suite, parameterized only by backend fixture, and
run it against every repository and store so that identical behavior on
SQLite and PostgreSQL is asserted rather than assumed.

## Key result

The same functional contract passes in full on SQLite and on a real
PostgreSQL, with the backend fixture as the only difference between the two
runs — and a store that works on one backend only fails the suite.

## Scope

- A shared contract harness with per-backend fixtures.
- Coverage of create, get, list, update, delete, upsert, and pagination.
- Transactions, rollback, and uniqueness violations.
- Equivalent error behavior across backends.
- Concurrency.
- Tenant isolation.
- Migrations.
- Timestamp and JSON round-tripping.
- Behavior after a restart.
- Application to every repository and to the E51-E55 stores.

## Out of scope

- Adding the PostgreSQL service to CI (E57-S1) — this epic builds the suite;
  E57 makes it run on every pull request.
- Performance and latency assertions, which belong to E60-S4.
- Retrieval quality benchmarking, which remains its own open Beta criterion.
- Replacing the stores' own unit tests; the contract suite complements them.

## Stories

### E56-S1 — Contract harness and backend fixtures

Subtasks:
- `E56-S1-T1`: build the harness so a contract case is written once and
  executed against each backend through a fixture, with no per-backend
  branching inside the case bodies.
- `E56-S1-T2`: provide a real PostgreSQL fixture that applies migrations to a
  clean database per run and tears it down, plus the SQLite fixture; make an
  unavailable PostgreSQL an explicit, visible skip with a named reason rather
  than a silent pass.
- `E56-S1-T3`: reconcile with `backend/sdk/testing.py:30` and the
  `DurableStore` alias so the SDK harness is not silently SQLite-only,
  coordinating with E49-S4-T3.

| Criterion | Detail |
| --- | --- |
| Functional | One contract case executes on both backends via fixture parameterization |
| Non-functional | No backend conditionals inside contract cases; skips are explicit and named, never silent |
| DoR (specific) | E49 merged |
| DoD (specific) | A trial contract case running green on both backends |
| Dependencies | E49, E50 |

### E56-S2 — Repository behavior contract

Subtasks:
- `E56-S2-T1`: CRUD and upsert cases for every repository defined in
  `backend/persistence/base.py`, plus the E51-E55 stores.
- `E56-S2-T2`: pagination cases asserting stable ordering and no duplicated
  or skipped rows across pages — the property E44-S3 introduced and which
  must now hold identically on both backends.
- `E56-S2-T3`: transactions, rollback, uniqueness violations, and equivalent
  error behavior — a uniqueness breach must raise the same shared exception
  type on both backends, which is what E49-S1-T2's error mapping exists for.

| Criterion | Detail |
| --- | --- |
| Functional | Every repository and ported store passes the same CRUD, pagination, transaction, and error contract on both backends |
| Non-functional | Error equivalence is asserted on the shared exception type, not on backend-specific messages |
| DoR (specific) | E56-S1 merged; E51-E55 merged |
| DoD (specific) | Full contract green on both backends; a deliberately backend-specific change fails it |
| Dependencies | E56-S1, E51-E55 |

### E56-S3 — Concurrency, isolation, migrations and restart

Subtasks:
- `E56-S3-T1`: concurrency cases covering the invariants E51-E55 established
  — quota consumption, lease acquisition, secret rotation, decision
  resolution, environment limits, step transitions — expressed once and run
  on both backends.
- `E56-S3-T2`: tenant isolation cases for every tenant-scoped table,
  including the thirteen from E50, asserting both directions of the
  boundary.
- `E56-S3-T3`: migration cases (up, down, idempotent re-run) and
  behavior-after-restart cases, proving durability rather than in-process
  state.

| Criterion | Detail |
| --- | --- |
| Functional | Concurrency invariants, tenant isolation, migration round trips, and post-restart durability hold on both backends |
| Non-functional | Concurrency cases assert invariants deterministically, not by timing; SQLite cases account for its single-writer model without weakening the assertion |
| DoR (specific) | E56-S2 merged |
| DoD (specific) | Full contract suite green on both backends, including concurrency and isolation |
| Dependencies | E56-S2, E50-S4 |

## Contracts and decisions

### Architectural decisions required

- No new ADR. This epic asserts contracts already defined by E8's repository
  protocols and by ADR-010's isolation model.
- One judgement call to record in the epic rather than an ADR: where SQLite
  genuinely cannot match PostgreSQL semantics — notably its single-writer
  concurrency model — the contract states the intended behavior for each
  backend explicitly instead of weakening the assertion to the lowest common
  denominator. Any such divergence is named in the suite, not implicit.

### Security and multitenancy

- Tenant isolation is the highest-value part of this suite: it is the only
  place where the RLS policies from E50-S4 and the SQLite predicate path from
  `tenancy.py` are compared against each other.
- Isolation cases must assert both directions — tenant A cannot read B, and B
  cannot read A — so a policy that denies everything cannot pass by
  accident.

### Migration strategy

- No schema change. The suite exercises the migrations E50 created.
- The PostgreSQL fixture applies migrations to a clean database per run, so
  the suite also continuously validates that a from-empty migration works.

### Compatibility and rollback

- This epic adds tests only; there is nothing to roll back beyond removing
  them.
- Its immediate effect is to surface pre-existing divergences. Any failure it
  exposes in already-merged code is a real defect and is fixed in the owning
  epic, not by relaxing the contract.

## Testing and observability

This epic *is* the test work. Its own quality gates:
- A deliberately introduced backend-specific behavior must fail the suite —
  the suite's own negative control.
- No contract case may contain a backend conditional.
- Skips must be explicit and named, never silent, so a PostgreSQL-less run
  cannot be mistaken for a passing one.

Observability: the suite reports which backend each case ran against, so CI
output distinguishes "passed on both" from "passed on SQLite, skipped
PostgreSQL" — the exact ambiguity that hid the current divergence.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| PostgreSQL unavailable, suite silently skips | Green CI with no PostgreSQL coverage — the current failure mode | Explicit named skips (E56-S1-T2); E57 makes PostgreSQL mandatory in CI |
| Contract weakened to the lowest common denominator | Parity asserted but meaningless | Named per-backend expectations where semantics genuinely differ, rather than removing the assertion |
| Suite duplicates existing store unit tests | Maintenance burden, slow runs | Contract covers cross-backend behavior; store tests keep covering store-specific logic |
| Flaky concurrency cases | Suite distrusted and eventually ignored | Assert invariants, never timing (E56-S3-T1) |

## DoR / DoD

- **DoR:** E49 and E50 merged; E51-E55 merged for the store portions; a real
  PostgreSQL available locally.
- **DoD:** all three story DoDs met; the full contract passes on both
  backends; the negative control fails as expected; no silent skips;
  `docs/v2_platform/progress.md` updated; no push or PR without explicit
  authorization.

## Exit evidence

1. Contract suite output for the SQLite run and the PostgreSQL run, showing
   the same case list passing on both.
2. Negative-control output: a deliberately backend-specific change failing
   the suite.
3. Tenant isolation results for all thirteen E50 tables, both directions.
4. Migration round-trip and post-restart case output.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`, `docs/feature_matrix.md`
(persistence rows), `CONTRIBUTING.md` if the contract suite becomes a
required local check.

Code: `backend/tests/` (contract harness and cases),
`backend/sdk/testing.py`, `backend/persistence/database.py` (the
`DurableStore` alias, jointly with E49-S4-T3).
