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

Secrets materialize only inside the E32 environment's process, as
environment variables resolved at `command_sandbox()` time -- never
through model context or plan/patch artifacts.

- `EnvironmentProfile.env_allowlist` (E32-S2's own "ambient credentials
  denied unless named here" gate) is reused as the injection declaration
  surface: no second allowlist mechanism was introduced.
  `EnvironmentManager.resolve_secrets_for_profile(handle)` resolves each
  allowlisted name against `SecretReference(tenant_id=handle.tenant_id,
  project=handle.profile.profile_id, name=name)` -- scoped to the
  *profile*, a stable admin-provisioned unit, not the run id (fresh per
  run, so nothing could ever be pre-created against it). A name with no
  matching stored secret is silently skipped, not an error -- not every
  allowlisted env var need be secret-backed.
- `CompositeActionRunner.bind_environment()` (`backend/execution/runner.py`)
  calls `resolve_secrets_for_profile()` once per binding (not once per
  dispatched action) and threads the resulting `dict[str, str]` through
  `ValidationJob.extra_env` (`backend/validation/models.py`) into
  `SandboxRunner._run_docker`/`_run_local`
  (`backend/validation/sandbox.py`) as `--env NAME=value` pairs / a merged
  subprocess `env=`. The value exists only as a local dict handed straight
  to the subprocess call -- it is never attached to any other object.

### Redaction (E33-S2-T2)

Exact-value redaction only (`backend/secret_store/redaction.py`) --
**guaranteed** for every value this process has actually resolved from the
secret store; entropy-based detection of unknown secret-shaped strings is
explicitly out of scope (**best-effort would be the wrong word: it simply
is not attempted**), documented here rather than silently omitted.

- `SecretRedactor` — built from one environment's exact
  `{value: SecretReference}` map (populated by
  `resolve_secrets_for_profile`). `EnvironmentManager.collect_artifacts()`
  scrubs every task's stdout/stderr transcript and diff with it *before*
  persistence (`backend/environments/manager.py`) -- redaction happens
  before the write, not at display time.
- A broader, process-wide safety net
  (`register_live_secret_value`/`redact_event_data`) scrubs every value
  this process has ever resolved from **every** emitted event's `data`
  payload, inside `emit_event()` itself (`backend/events/runtime.py`) --
  every event producer is protected, including ones with no direct
  relationship to `EnvironmentManager` (e.g. `run.timeline.*`), without
  each one remembering to redact its own payload.
- **Overhead:** redaction is `O(known-values × text-length)` exact
  substring replacement per emitted event/persisted artifact; the known-value
  set is small (only values actually resolved), so this is not a measured
  bottleneck at Beta scale.

### Leak fixture (E33-S2-T3)

A task that echoes an injected secret's exact value into its stdout/diff
has that value redacted from the persisted artifact *and* triggers a
durable `secret.leak.suspected` audit event (`tenantId`/`project`/`name`/
`runId`/`location`, never the value) via
`EnvironmentManager._audit_leaks()`. Covered by
`backend/tests/unit/environments/test_manager.py::test_collect_artifacts_redacts_leaked_secret_and_audits`.

## Rotation, revocation & audit (E33-S3)

- **Rotation takes effect on next provision (E33-S3-T1).** Nothing caches
  a resolved value across provisions: `EnvironmentManager.resolve_secrets_for_profile`
  re-resolves from the store on every `bind_environment()` call, so a
  secret rotated between two provisions is picked up by the next one
  automatically — no cache to invalidate, no propagation delay. An
  environment already bound before a rotation keeps the value it already
  resolved for its own lifetime (unsurprising: it never re-resolves mid-run).
  Covered by `test_rotated_secret_takes_effect_on_next_provision`
  (`backend/tests/unit/environments/test_manager.py`).
- **Revocation fails closed everywhere, not just at the store.**
  `SecretStore.resolve_latest_active` raises `SecretRevokedError` once a
  reference's latest version is revoked — there is no path back to an
  older active version. At the injection boundary, a revoked (or simply
  never-created) allowlisted name is *skipped*, not raised: an environment
  provisions successfully with one fewer resolved env var rather than
  failing the whole batch over one credential. Covered by
  `test_revoked_secret_is_skipped_on_next_provision` and
  `SecretService`'s own `test_revoke_fails_resolution_closed`.
- **Audit (E33-S3-T2).** Every `create`/`rotate`/`revoke`/`resolve`
  durably emits a `secret.*` event (`backend/events/catalog.py`:
  `secret.created`, `secret.rotated`, `secret.revoked`, `secret.resolved`,
  plus `secret.leak.suspected` for the E33-S2 leak fixture) carrying the
  scoped reference, version, and actor — never a value. Covered by
  `test_rotate_emits_secret_rotated_event_without_a_value` and
  `test_revoke_emits_secret_revoked_event_without_a_value`
  (`backend/tests/unit/secret_store/test_service.py`), alongside the
  create/resolve coverage from E33-S1/S2.
- **Beta gate wiring (E33-S3-T3).** The v2.0-beta gate's "no plaintext
  secrets" criterion is *evidenced* here (redaction tests +
  reference-only audit trail); adding the actual checklist row to
  `docs/v2_platform/progress.md` §18.9 is E35-S1-T1's job (E35 — Beta
  Readiness Gates & Evidence), which explicitly owns expanding that gate
  with the E32/E33/E34 criteria — E33 supplies the evidence, not the
  checklist edit.
