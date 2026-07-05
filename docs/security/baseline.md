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

Run the local scanner from the container:

```bash
make run_secret_scanning
```

The scanner is dependency-free and checks repository text files for
high-confidence OpenAI, GitHub, AWS, and private-key patterns. It excludes
generated dependency/cache directories such as `.git`, `.venv`, `node_modules`,
and test caches.

The backend CI workflow runs the same scanner on every push and pull request.

## SCA / CVE Policy

CI uses Trivy filesystem scanning as the baseline software composition analysis
gate. The E0 policy is:

- block pull requests on `CRITICAL` vulnerabilities;
- ignore unfixed vulnerabilities at this baseline stage;
- keep scan runtime bounded to 3 minutes.

E11 can tighten this to high-severity and license policy gates when RBAC,
multi-tenant controls, and production release governance are in place.

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
