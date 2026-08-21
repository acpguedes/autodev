# Security Baseline

E0-S5 establishes the minimum security posture for local development, CI, and
self-hosted deployments.

## Secret Management

- Runtime secrets are injected through environment variables or the configured
  settings file. They must not be committed to the repository.
- `Settings.redacted_model_dump()` and the runtime config API redact known
  secret fields before returning or logging settings.
- `AUTODEV_API_TOKEN` enables bearer-token protection for the API. It is empty
  by default for local development and required when exposing the API beyond
  loopback.
- `AUTODEV_ENABLE_HSTS` is opt-in. Enable it only when the API is served over
  HTTPS or behind a trusted TLS-terminating proxy.

## Secret Scanning

Run the local scanner from the container — it mounts the entire working tree
read-only (`-v "$(CURDIR):/repo:ro"`), so uncommitted files are scanned too:

```bash
make run_secret_scanning
```

The scanner is dependency-free and checks repository text files for
high-confidence OpenAI, GitHub, AWS, and private-key patterns, across both
git-tracked and untracked-but-not-ignored files. It excludes generated
dependency/cache directories such as `.git`, `.venv`, `node_modules`, and
test caches.

The backend CI workflow runs the same scanner on every push and pull request.

### Allowlisting an intentional fixture

Some tests need credential-shaped values on purpose — proving that a provider's
`401 ... api_key=sk-... rejected` message never reaches a span is only
meaningful if the fixture actually looks like a key. Suppress those with an
inline marker on the same line:

```python
raise VendorError("401 Unauthorized: api_key=sk-example... rejected")  # pragma: allowlist secret
```

Rules and rationale:

- **The marker is line-scoped**, never file- or directory-scoped. Excluding
  `backend/tests/` wholesale would also hide a real credential committed in a
  fixture, which is the failure mode the gate exists to prevent.
- **Every suppression is visible and auditable.** It appears in the diff that
  introduces it and stays greppable:
  `grep -rn "pragma: allowlist secret"`. Treat a new one in review as a claim
  that needs justifying, not as boilerplate.
- **The scanner cannot allowlist itself.** `backend/security/secrets.py` and
  its test module treat the marker as ordinary text, so neither can use it to
  hide a finding in itself.
- The convention matches [`detect-secrets`](https://github.com/Yelp/detect-secrets),
  so the annotations survive a future migration to it.

Use it only for values that are provably not real credentials. A value that
*might* be live belongs in an environment variable, never in the repository.

## SCA / CVE and License Policy (tightened E11-S4)

CI uses Trivy filesystem scanning as the software composition analysis gate.
The zero-baseline E0 policy (`CRITICAL`-only, vulnerabilities-only,
unfixed-ignored) has been tightened by E11-S4 now that the RBAC/multi-tenant
and production-governance prerequisites it deferred on are landing:

- block pull requests on `HIGH` **and** `CRITICAL` findings;
- cover **both vulnerabilities and licenses** (`scanners: vuln,license`), not
  vulnerabilities only;
- do **not** ignore unfixed vulnerabilities — a HIGH/CRITICAL finding with no
  published patch still fails the gate;
- keep scan runtime bounded to 3 minutes.

Exceptions are possible only through `.trivyignore.yaml`, and only when
`scripts/validate_security_exceptions.py` accepts them: every entry needs a
non-empty `id`, a `statement` of the form `approved-by=<identity>;
reason=<rationale>`, and an unexpired `expires_at`. `make
validate_security_exceptions` runs this locally; CI runs it as a required
step immediately before the Trivy scan (`.github/workflows/ci-backend.yml`,
`security-baseline` job) — a malformed or expired exception fails the build
before Trivy even runs, rather than the exception silently not applying.

## HTTP Security Headers

The API adds these headers by default:

- `Content-Security-Policy`
- `Permissions-Policy`
- `Referrer-Policy`
- `X-Content-Type-Options`
- `X-Frame-Options`

`Strict-Transport-Security` is emitted only when `AUTODEV_ENABLE_HSTS=true`.

## Plugin Permission Isolation

Plugins run under a default-deny permission model (v2 E1-S3): no filesystem,
network, subprocess, or secrets access unless declared in `plugin.yaml` and
granted by the host, all Host API access is brokered, and denials raise
`plugin.permission.denied` audit events. See
[`docs/plugins/permissions.md`](../plugins/permissions.md) for the full model.

Production additionally enforces the trusted-only in-process plugin boundary
(ADR-020, E11-S4): an `in-process` plugin needs an explicit operator trust
grant (`AUTODEV_TRUSTED_IN_PROCESS_PLUGINS`), and is rejected even when
trusted if it declares `runtime.isolation` or requests a privileged
permission block. See
[`docs/v2_platform/decisions/ADR-020-trusted-in-process-plugin-boundary.md`](../v2_platform/decisions/ADR-020-trusted-in-process-plugin-boundary.md).

## Beta hardening additions

The E0-S5 baseline above has since been extended by the v2.0 Beta wave.
Full detail lives in [`docs/security.md`](../security.md); summary:

- **Execution permission & policy engine (E14-S2, ADR-022).** Every
  dispatched execution action is gated by `PolicyService.evaluate`
  (`backend/execution/policy.py`) with category-scoped allow/deny rules
  and a durable per-decision audit trail; fails closed in production for
  a tenant with no stored policy.
- **Multi-tenant quotas & run budgets (E11-S3, ADR-019).** A durable
  per-tenant quota/budget layer (`backend/quotas/`) enforces concurrency
  leases, storage reservations, monthly usage windows, and request-rate
  limits; the Agent Runtime and Reasoning Engine both fail closed on
  budget exhaustion.
- **Isolated execution environments (E32, ADR-013).** A backend-agnostic
  `EnvironmentBackend` protocol (`backend/environments/`) with a hardened
  container as the Beta default, fail-closed network/filesystem policy
  checks, and audited provision/access/retire events.
- **Secrets & credential governance (E33, ADR-014).** A scoped-reference,
  encrypted-at-rest secret store (`backend/secret_store/`) with
  redaction-before-persistence and a full rotation/revocation/audit
  trail. Detailed in [`docs/security/secrets.md`](secrets.md).
