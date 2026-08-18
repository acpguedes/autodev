# Secrets & Credential Governance (Beta) — E33

Canonical source: `docs/architecture/v2_platform_reference.md` §16.1.2,
`docs/v2_platform/phases/e33_secrets_credential_governance.md`,
`docs/v2_platform/decisions/ADR-014-secret-store-format.md` (Accepted).

## What this delivers

E33 owns the Beta secret layer: scoped-reference secret storage that never
returns a raw value, injection into E32 execution environments without
plaintext exposure to agents/logs, redaction across logs/events/artifacts,
and rotation/revocation with full audit.

Code: `backend/secret_store/`.

- `contracts.py` — `SecretReference` (`tenant_id`/`project`/`name`),
  `SecretMetadata` (reference + version + status + timestamps, never a
  value), `SecretStatus` (`active`/`superseded`/`revoked`),
  `SecretBackendKind` (`encrypted_database`, ADR-014's Beta default),
  typed errors `SecretNotFoundError`/`SecretRevokedError`.
- `crypto.py` — envelope encryption via
  `backend.auth.crypto.derive_fernet` (the same Fernet primitive already
  used for browser refresh tokens), keyed by
  `AUTODEV_SECRET_ENCRYPTION_KEY`. Unset (local mode) derives an
  ephemeral per-process key, mirroring
  `AUTODEV_SESSION_ENCRYPTION_KEY`'s own local-mode fallback.
- `store.py` — `SecretStore`, a durable SQLite-backed, versioned store
  (`create`/`rotate`/`revoke`/`resolve_latest_active`/`get_metadata`/
  `list_metadata`) scoped to `(tenant_id, project, name, version)`.
  `resolve_latest_active` is the *only* method that ever returns
  ciphertext, and only the injection path (E33-S2) calls it.
- `service.py` — `SecretService`: crypto + store + durable
  `secret.*` audit events for every create/rotate/revoke/resolve.

## RBAC (E33-S1-T3)

Two scopes separate managing a secret from merely being permitted to have
one injected into your own execution:

| Scope | Tier | Grants |
| --- | --- | --- |
| `secret:use` | VIEWER+ | Read a secret's metadata (`GET /v2/secrets`, `GET /v2/secrets/{project}/{name}`) — never a value. |
| `secret:manage` | ADMIN+ | Create/rotate/revoke (`POST /v2/secrets`, `.../rotate`, `.../revoke`). |

Every request is scoped to the caller's own `tenant_id` (from the
authenticated `PrincipalV2`, E11-S2) — cross-tenant resolution is
impossible by construction, since no request parameter ever selects a
different tenant.

## REST API (`backend/api/routers/secrets_v2.py`)

Every response model (`SecretMetadataV2`, `SecretListV2`) carries metadata
fields only — there is no field a handler could accidentally populate with
a value. "No API returns a stored value" therefore holds structurally, not
just by handler discipline.

| Route | Scope | Behavior |
| --- | --- | --- |
| `POST /v2/secrets` | `secret:manage` | Create; 409 if the reference already exists (use rotate). |
| `POST /v2/secrets/{project}/{name}/rotate` | `secret:manage` | New version; 404 if unknown. |
| `POST /v2/secrets/{project}/{name}/revoke` | `secret:manage` | Fail-closed revoke; 404 if unknown. |
| `GET /v2/secrets` | `secret:use` | List the caller's tenant's secrets (metadata). |
| `GET /v2/secrets/{project}/{name}` | `secret:use` | One secret's metadata; 404 if unknown. |

## CLI (`autodev secrets`)

Mirrors `autodev quotas get`/`set`. `create`/`rotate` read the raw value
from stdin (`--value-stdin`), never a positional/flag argument — CLI
arguments are visible in shell history and process listings.

## Encryption-at-rest (ADR-014)

Database-encrypted-at-rest with envelope keys (Fernet) is the Beta
default; the ciphertext format and backend are swappable behind
`SecretBackendKind`/`SecretStore` without touching
`SecretReference`/`SecretMetadata` or any caller — see ADR-014 for the
full trade-off table and the honest scope reduction (Postgres RLS and an
external KMS/vault backend are deferred, not silently dropped).

## Injection into execution environments (E33-S2)

<!-- Filled in by E33-S2: env-var injection via ValidationJob.extra_env,
     EnvironmentManager wiring, redaction across logs/events/artifacts,
     the leak-fixture test. -->

## Rotation, revocation & audit (E33-S3)

Every `create`/`rotate`/`revoke`/`resolve` durably emits a `secret.*`
event (`backend/events/catalog.py`: `secret.created`, `secret.rotated`,
`secret.revoked`, `secret.resolved`, plus `secret.leak.suspected` for the
E33-S2 leak fixture) carrying the scoped reference, version, and actor —
never a value. `resolve_latest_active` fails closed with
`SecretRevokedError` once a reference is revoked; there is no path back to
an older active version.
