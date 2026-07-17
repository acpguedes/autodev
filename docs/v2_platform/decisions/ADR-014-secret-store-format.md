# ADR-014 — Secret Store Format

- **Status:** Proposed (decision pending — do not resolve silently)
- **Date:** 2026-07-17
- **Epic:** E33
- **Stories:** E33-S1..S3 (implementable behind the contract while pending)
- **Decide by:** before E33-S2 starts

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

## Recommendation (not a decision)

Database-encrypted-at-rest with envelope keys as the self-host default,
with `secret_backend` as a contract-tested extension point (E12) so
external KMS/vault plugs in without core changes. Encrypted file store
only if the embedded/local profile (E34-S2) demands zero-Postgres setups.

## Consequences (of the pending state)

- E33-S1 ships the contract plus the default backend; values are write-only
  through the API regardless of format.
- E33-S2 (injection/redaction) is format-independent and proceeds.
- Tracked in the E35-S3 open-decisions register with owner and milestone.
