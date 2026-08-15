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
