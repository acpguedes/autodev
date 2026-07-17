# E33 — Secrets & Credential Governance (Beta)

**Wave:** v2.0-beta — "plataforma completa em produção controlada".
**Status:** Not started · **Stories:** 0/3 complete
**Depends on:** E11 (RBAC, audit), E32 (execution environments — injection
target), E0 (config foundations)
**Enables:** governed real execution with credentials (E14 tasks that need
tokens), provider configuration without plaintext exposure, the v2.0-beta
gate on secret handling
**Canonical source:** `docs/architecture/v2_platform_reference.md` §16.1.2;
`docs/v2_platform/beta_gap_analysis.md`; ADR-014 (pending)

## Objective

Provide the Beta secret layer: a **secret store abstraction** whose
persistence format is a documented, pending decision (**ADR-014**: encrypted
file store vs database-encrypted-at-rest vs external KMS/vault), scoped
references (tenant/project) instead of values, **injection into execution
environments without plaintext exposure** to agents or logs, and redaction
across logs, traces, events and artifacts. The abstraction keeps the store
swappable so the ADR decision does not block Beta.

## Key result

A real task that needs a credential (e.g., a git token) receives it inside
the E32 environment via scoped injection; the value never appears in
prompts, logs, traces, events, diffs or artifacts; rotation invalidates the
old value platform-wide; and every secret access is audited.

## Stories

### E33-S1 — Secret store abstraction & format decision

Subtasks:
- `E33-S1-T1`: store contract — create/rotate/revoke/resolve by **scoped
  reference** (`tenant/project/name`); values write-only through the API;
  reads only by the injection path, never by general callers.
- `E33-S1-T2`: ADR-014 lifecycle — options (encrypted file store, DB
  encrypted at rest with envelope keys, external KMS/vault integration),
  trade-offs (self-host simplicity vs enterprise posture), recommendation
  and pending decision; default backend implemented behind the contract.
- `E33-S1-T3`: RBAC on secret operations (E11) — manage vs use permissions
  separated; tenant isolation enforced at the store boundary.

| Criterion | Detail |
| --- | --- |
| Functional | Secrets are created/rotated/revoked via scoped references; no API returns a stored value; cross-tenant resolution is impossible by construction |
| Non-functional | Backend swap requires no changes outside the secret layer; encryption-at-rest verified for the default backend |
| DoR (specific) | ADR-014 filed (may be `Proposed`); §16.1.2 reviewed |
| DoD (specific) | Contract + tenant-isolation tests; `docs/security/secrets.md` |
| Dependencies | E11, E0 |

### E33-S2 — Injection into execution environments & redaction

Subtasks:
- `E33-S2-T1`: injection path — secrets materialize only inside the E32
  environment (env var or file mount per profile declaration), resolved at
  provision time; never passed through model context or plan/patch
  artifacts.
- `E33-S2-T2`: redaction — known secret values/prefixes redacted from logs,
  run timeline events, traces and stored artifacts; redaction applied
  before persistence, not at display time.
- `E33-S2-T3`: leak fixture — a task that echoes a secret produces redacted
  logs/artifacts and a typed `secret.leak_suspected` audit event.

| Criterion | Detail |
| --- | --- |
| Functional | A task using an injected secret succeeds while the value is absent from prompts, logs, events, diffs and artifacts; the leak fixture is redacted and audited |
| Non-functional | Redaction overhead measured; documented limits (entropy-based detection is best-effort, exact-value redaction is guaranteed) |
| DoR (specific) | E33-S1, E32-S1 available |
| DoD (specific) | Injection + leak-fixture tests; redaction section in `docs/security/secrets.md` |
| Dependencies | E33-S1, E32-S1/S3 |

### E33-S3 — Rotation, revocation & audit

Subtasks:
- `E33-S3-T1`: rotation/revocation — new version takes effect on next
  provision; revoked secrets fail resolution closed with a typed error.
- `E33-S3-T2`: audit — every create/rotate/revoke/resolve emits an audit
  event (actor, scope, secret reference — never the value) into E11.
- `E33-S3-T3`: Beta gate wiring — gate criterion "no plaintext secrets"
  asserted from redaction tests + audit records.

| Criterion | Detail |
| --- | --- |
| Functional | Rotation invalidates the old value for subsequent runs; revoked references fail closed; the audit trail reconstructs who used which secret reference when |
| Non-functional | Audit events carry references only; no value material in any persisted record |
| DoR (specific) | E33-S1, E33-S2 landed |
| DoD (specific) | Rotation/revocation/audit tests; `docs/v2_platform/progress.md` updated |
| Dependencies | E33-S1, E33-S2, E11 |

## Contracts & decisions

- **ADR-014 — Secret store format** (pending): options, trade-offs,
  recommendation documented; decision does not block E33 because the store
  is contract-first.
- Extension point `secret_backend` gets a mandatory contract test (E12).

## DoR / DoD

- **DoR:** §16.1.2 reviewed; ADR-014 filed; gap analysis subsection
  approved.
- **DoD:** all story DoDs; `docs/security/secrets.md` published; v2.0-beta
  gate criteria (§18.9) reference E33 evidence; no push/PR without explicit
  authorization.
