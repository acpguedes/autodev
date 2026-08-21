# E52 — SecretStore on PostgreSQL

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E47: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/3
**Depends on:** E49 (persistence contract, row-lock primitive), E50-S1
(`secrets` migration), E33 / ADR-014 (secret store format and the
`SecretBackendKind` contract)
**Enables:** secret creation, rotation, revocation, and resolution to work in
the `prod` profile, and closes the PostgreSQL backend gap E33 explicitly
deferred.
**Canonical source:** this document, plus E33's own recorded deferral —
`docs/v2_platform/phases/e33_secrets_credential_governance.md` states that
"Postgres RLS-backed storage and a true external KMS/vault backend are
deferred behind the swappable `SecretBackendKind` contract". This epic closes
the first half of that deferral.

## Context and problem

`SecretStore` is SQLite-only and refuses a PostgreSQL URL
(`backend/secret_store/store.py:48`), while the `prod` profile requires one.
Secrets are therefore unusable in production — the subsystem that governs
credential handling is the one that cannot start.

This is not merely a missing backend. The `secrets` table holds ciphertext
for every tenant with no Row-Level Security, relying entirely on application
`WHERE` clauses for isolation. And rotation — the operation most likely to
run concurrently, since it is both scheduled and incident-driven — is
serialized today by `BEGIN IMMEDIATE`, which has no PostgreSQL equivalent.
Two concurrent rotations without a real lock can produce two "active"
versions or a version gap.

## Evidence in code

- `backend/secret_store/store.py:40-49` — private `_resolve_db_path`; `:48`
  raises `ValueError("SecretStore requires a sqlite:// DATABASE_URL")`.
- `backend/secret_store/store.py:83` — `sqlite3.connect(...)`.
- `backend/secret_store/store.py:91` — `secrets` table created by
  `CREATE TABLE IF NOT EXISTS`, outside `MigrationRunner`, therefore
  unversioned.
- `backend/secret_store/store.py:140, 188, 241` — `BEGIN IMMEDIATE` on the
  create, rotate, and revoke paths; the docstring at `:11-12` says it mirrors
  `QuotaStore`'s pattern, which E51 shows is itself misdocumented.
- `backend/secret_store/service.py:50` — `self._store = store or
  SecretStore()`, no injection point in production.
- `backend/persistence/migrations/postgres_versions.py` — no `secrets`
  table; RLS covers only the eleven core/plan/code tables.
- `backend/cli.py:127-173` — `secrets create|rotate|revoke|list` are live CLI
  commands, so the broken production path is directly operator-facing.

## Objective

Port the versioned secret store to run on both backends through the E49
contract, with rotation and revocation that stay correct under concurrency,
and with tenant isolation enforced by the database rather than by query
discipline.

## Key result

Two concurrent rotations of the same secret produce one coherent version
chain — exactly one active version, no gap, no duplicate — and no plaintext
value is ever written to the database, a log, or an event.

## Scope

- Creation, rotation, revocation, and resolution of the latest active
  version on both backends.
- Ciphertext-only storage, preserved from the current design.
- Concurrency control for rotation, replacing `BEGIN IMMEDIATE`.
- Version constraints that make an inconsistent chain impossible at the
  schema level, not only in application logic.
- Isolation by tenant, project, and name.
- Audit of secret operations.
- Fail-closed behavior when the backend is unavailable.
- Compatibility with the existing encryption key and already-stored
  ciphertext.

## Out of scope

- An external KMS/vault backend — the other half of E33's deferral, still
  behind `SecretBackendKind`, and not required for PostgreSQL parity.
- Changing the encryption scheme or key management (ADR-014 stands).
- The `secrets` migration itself (E50-S1-T2).
- Migrating existing SQLite secret rows to PostgreSQL (E58-S2, which must
  carry ciphertext across unchanged).

## Stories

### E52-S1 — Versioned secret storage on both backends

Subtasks:
- `E52-S1-T1`: move `SecretStore` onto the E49 contract — remove
  `sqlite3.connect`, the private `_resolve_db_path`, and the PostgreSQL
  rejection guard; drop `_create_schema` in favour of the E50-S1 migration.
- `E52-S1-T2`: port create, rotate, and revoke so each is one code path
  across backends, using the contract's upsert and `RETURNING` rather than
  SQLite-specific syntax.
- `E52-S1-T3`: preserve ciphertext-only storage and verify compatibility with
  the existing key — a secret written by the current SQLite implementation
  must decrypt unchanged after the port.

| Criterion | Detail |
| --- | --- |
| Functional | create/rotate/revoke/resolve behave identically on both backends; `prod` can construct `SecretStore` |
| Non-functional | No `sqlite3` import remains in `backend/secret_store/store.py`; the column stores ciphertext only |
| DoR (specific) | E49-S2 and E50-S1 merged |
| DoD (specific) | Existing secret tests green on both backends; a pre-port ciphertext decrypts after the port |
| Dependencies | E49, E50-S1, E33 |

### E52-S2 — Rotation concurrency and version integrity

Subtasks:
- `E52-S2-T1`: replace `BEGIN IMMEDIATE` on the rotation path with the E49
  lock primitive, taking a row lock on the secret's version chain.
- `E52-S2-T2`: enforce the "exactly one active version" invariant with a
  database constraint, so a logic error cannot create a second active
  version even outside the intended code path.
- `E52-S2-T3`: make rotation idempotent under retry — a retried rotation must
  not create an extra version.

| Criterion | Detail |
| --- | --- |
| Functional | Concurrent rotations serialize; the chain has exactly one active version and no gaps |
| Non-functional | The invariant is enforced by a constraint, not only by application code |
| DoR (specific) | E52-S1 merged |
| DoD (specific) | Concurrency test: N concurrent rotations of one secret leave a coherent chain |
| Dependencies | E52-S1 |

### E52-S3 — Isolation, audit and fail-closed

Subtasks:
- `E52-S3-T1`: isolation tests across tenant, project, and name — including
  the negative case where two tenants use the same secret name.
- `E52-S3-T2`: verify audit coverage for create, rotate, revoke, and resolve,
  and assert that no audit record, log line, or event carries a plaintext
  value.
- `E52-S3-T3`: fail-closed behavior — when the store is unreachable,
  resolution must deny rather than fall back to an empty or cached value.

| Criterion | Detail |
| --- | --- |
| Functional | Same-named secrets in different tenants never collide or leak; unavailability denies |
| Non-functional | No plaintext in database, logs, events, or audit records, asserted by test |
| DoR (specific) | E52-S2 merged; E50-S4 RLS applied to `secrets` |
| DoD (specific) | Isolation, no-plaintext, and fail-closed tests green |
| Dependencies | E52-S2, E50-S4 |

## Contracts and decisions

### Architectural decisions required

- No new ADR. ADR-014 defines the secret store format and `SecretBackendKind`
  keeps the backend swappable; this epic adds the PostgreSQL implementation
  E33 deferred. If the port requires a format change, that would need an ADR
  superseding ADR-014 — the port is expected not to.

### Security and multitenancy

- This is the highest-sensitivity table in the program. RLS on `secrets`
  (E50-S4) plus `FORCE ROW LEVEL SECURITY` is what turns isolation from a
  convention into a guarantee.
- Ciphertext only: the plaintext value must never reach the database layer in
  storable form. `backend/ops/bootstrap.py` already never handles a plaintext
  value by design; the port must not weaken that.
- Fail-closed is mandatory. A secret store that cannot be reached must not
  resolve to empty — that would silently downgrade callers that treat an
  absent secret as "no credential required".
- Audit records identify *which* secret and *which* operation, never the
  value.

### Migration strategy

- No schema work here (E50-S1-T2).
- The store stops creating its own table; existence becomes the migration
  runner's responsibility, which also brings `secrets` under
  `schema_version` and `SchemaVersionMismatchError` protection for the first
  time.

### Compatibility and rollback

- Existing ciphertext must decrypt unchanged (E52-S1-T3) — this is the
  compatibility gate for the whole epic.
- SQLite local-first behavior is preserved.
- Rollback is reverting the port. Because E58 has not yet moved data, an
  existing SQLite secret store remains authoritative and intact.

## Testing and observability

Tests required:
- Existing secret suites, green on both backends.
- Pre-port ciphertext decrypting after the port.
- Concurrent rotation leaving a coherent version chain.
- Retried rotation creating no extra version.
- Isolation across tenant, project, and name, including same-name collision.
- No plaintext in database, logs, events, or audit.
- Fail-closed on backend unavailability.

Observability:
- Secret operations remain audited through the existing E11-S2 access-audit
  path.
- No new metric may carry a secret name that would identify a credential in a
  low-cardinality label; follow the existing cardinality policy in
  `docs/ops/observability.md`.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Concurrent rotation creates two active versions | Callers resolve inconsistent credentials; a revoked secret stays live | Row lock (E52-S2-T1) plus a database constraint (E52-S2-T2), so neither alone is the single point of failure |
| Plaintext leaks into a log or event during the port | Credential disclosure | Explicit no-plaintext assertions in E52-S3-T2, extending the existing E33 discipline |
| Ciphertext incompatibility after the port | Every stored secret becomes undecryptable | Compatibility test is a DoD gate on the first story, before rotation work begins |
| Fail-open on backend unavailability | Silent authorization bypass | E52-S3-T3 asserts denial, not empty resolution |
| `secrets` reaches PostgreSQL before RLS lands | A window with application-only isolation | E52-S3 hard-depends on E50-S4 |

## DoR / DoD

- **DoR:** E49-S2 and E50-S1 merged; ADR-014 re-read and confirmed unchanged;
  a real PostgreSQL available to the test suite.
- **DoD:** all three story DoDs met; `prod` constructs and uses
  `SecretStore` on PostgreSQL; concurrent rotation proven safe; no plaintext
  anywhere; fail-closed proven; `docs/v2_platform/progress.md` updated; no
  push or PR without explicit authorization.

## Exit evidence

1. Concurrent-rotation test output showing one active version and no gaps.
2. Decryption of a ciphertext written before the port.
3. Isolation test output for same-named secrets in two tenants.
4. No-plaintext assertion output across database, logs, events, and audit.

## Affected documents and code

Documents: `docs/v2_platform/progress.md`, `docs/security/secrets.md`,
`docs/feature_matrix.md` (secret store row),
`docs/v2_platform/runbooks/e35_secret_leak_rotation.md` (rotation procedure
under a PostgreSQL backend).

Code: `backend/secret_store/store.py`, `backend/secret_store/service.py`,
`backend/cli.py` (only if command behavior changes).
