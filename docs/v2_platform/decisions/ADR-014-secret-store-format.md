# ADR-014 — Secret Store Format

- **Status:** Accepted
- **Date:** 2026-07-17 (proposed) / 2026-08-17 (accepted)
- **Epic:** E33
- **Stories:** E33-S1..S3 (implemented behind the contract)

## Context

Beta requires secrets handled as scoped references with injection into
execution environments and guaranteed redaction (`v2_platform_reference.md`
§16.1.2; §18.9 criterion 11). The persistence format determines the
self-host posture and enterprise integration path, and must be swappable
behind the E33 store contract.

## Options

| Option | Pros | Cons |
| --- | --- | --- |
| Encrypted file store (age/sops-style, key on host) | Simplest self-host; no extra service; easy backup | Key management on the operator; weak multi-node story; rotation is manual-ish |
| Database encrypted at rest (envelope encryption, master key via env/KMS) | One operational store (Postgres, ADR-001); tenant scoping via existing RLS; auditable in-band | Master-key custody still needed; DB compromise blast radius mitigated only by envelope design |
| External KMS/vault (HashiCorp Vault, cloud KMS) | Strongest posture; rotation/audit native; enterprise-friendly | Heavy dependency for self-host Beta; network path to secrets; setup complexity |

## Decision

Database-encrypted-at-rest with envelope keys is the Beta self-host
default: values are encrypted with Fernet (authenticated symmetric
encryption) before ever reaching the durable store, reusing the crypto
primitive already established for browser refresh tokens
(`backend.auth.crypto.derive_fernet`, keyed by an operator-provided
setting) rather than introducing a second cipher — see
`backend.secret_store.crypto`. `backend.secret_store.contracts.SecretBackendKind`
is the swappable extension point (`ENCRYPTED_DATABASE` today); an external
KMS/vault backend can be added as a second enum member and
`SecretService`/`SecretStore` implementation without changing
`SecretReference`/`SecretMetadata` or any caller.

**Scope reduction, stated explicitly (see `docs/security/secrets.md`):**
the Beta implementation stores ciphertext in its own bounded SQLite-backed
table (`backend.secret_store.store.SecretStore`), matching the precedent set by
the two most recent Beta-epic stores (`backend.quotas.store.QuotaStore`,
`backend.environments.store.EnvironmentStore`) rather than the original E0
`backend.persistence.migrations` runner. Postgres Row-Level-Security-backed
storage (this ADR's original "one operational store, tenant scoping via
existing RLS" framing) and a true external KMS/vault backend are deferred —
neither blocks Beta because the contract is swappable, per this ADR's own
stated design.

## Consequences

- E33-S1 ships the contract plus the default backend; values are write-only
  through the API regardless of format — every response model in
  `backend.api.routers.secrets_v2` carries metadata only, structurally
  incapable of returning a value.
- E33-S2 (injection/redaction) is format-independent and proceeds
  unaffected by this decision.
- A future KMS/vault backend, or a Postgres/RLS-backed default, is a
  contract-compatible swap behind `SecretBackendKind` — not an ADR
  revision.
