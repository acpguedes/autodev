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
