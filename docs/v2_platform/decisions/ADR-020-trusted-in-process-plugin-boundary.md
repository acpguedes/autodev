# ADR-020: Trusted-Only In-Process Plugin Boundary

- **Status:** Accepted
- **Date:** 2026-08-15
- **Authors:** AutoDev maintainers
- **Related epic:** E11-S4
- **Supersedes/Relates to:** None

## Context

The Plugin Host's permission broker (E1-S3) mediates *capability access* — it
decides whether an already-loaded plugin may reach a given file, network
endpoint, command, or secret. It does not, and cannot, provide *process
isolation*: an `in-process` plugin is Python code imported directly into the
backend's own interpreter (`backend/plugins/host.py::_load_entrypoint`). Given
that, a plugin manifest declaring narrow permissions is not a security
boundary by itself — arbitrary in-process code can still call into any part of
the running process outside the broker's mediated surface (module internals,
other plugins' loaded state, process memory). The `subprocess` and `wasm`
loaders are real isolation boundaries; `in-process` is not.

Today, any manifest-valid plugin installs identically whether the process is
running a developer's laptop or a production deployment. Production needs a
policy that reflects the real trust boundary the `in-process` loader provides
(none) without changing the manifest schema, the host API contract, or how
local development works.

## Decision

Production (`AUTODEV_PROFILE=prod`) enforces a trusted-only in-process plugin
boundary at install time, inside `PluginHost._compatibility_reason`:

1. An `in-process` plugin must have its id present in the operator-configured
   allowlist `AUTODEV_TRUSTED_IN_PROCESS_PLUGINS` (parsed by
   `Settings.trusted_in_process_plugin_ids()`). Absence is rejected
   unconditionally — trust is opt-in, never inferred from the manifest.
2. Even an explicitly trusted `in-process` plugin is rejected if its manifest
   declares `runtime.isolation` to anything other than unset/`"none"` — the
   `in-process` loader cannot satisfy a claimed isolation strategy, so the
   claim itself is treated as a policy violation rather than silently ignored.
3. Even an explicitly trusted, non-isolated `in-process` plugin is rejected if
   it requests any *privileged* permission block: `network.egress`,
   `filesystem.read`, `filesystem.write`, `exec.commands`, or `secrets`. A
   plugin that needs any of those capabilities in production must use the
   `subprocess` or `wasm` loader, where the broker's mediation is backed by a
   real process boundary.

Host API and event-bus access granted through `ScopedHostApi` remain brokered
per plugin.yaml exactly as today, and do not, by themselves, make a plugin
"privileged" under this rule — declaring an extension point or subscribing to
platform events is not one of the five permission blocks above.

Local (`AUTODEV_PROFILE=local`) development is unaffected: the trust check is
a no-op outside production, matching current install behavior exactly.

The plugin manifest schema, `PluginManifest`/`RuntimeSpec`/`PermissionSpec`,
and `hostApi` are unchanged. This is a host-side security policy, not a
contract change — nothing a plugin author writes in `plugin.yaml` opts a
plugin into or out of enforcement.

## Alternatives considered

1. **Self-asserted `trusted: true` manifest field** — rejected because trust
   would then be declared by the plugin author, i.e. by the same party the
   policy exists to constrain; it adds a manifest schema change for a
   guarantee it cannot actually provide.
2. **Rely on Python import interception as isolation** — rejected; intercepting
   `import` calls does not prevent already-imported code from reaching
   arbitrary process state through normal attribute access, closures, or
   monkeypatching. It is not a security boundary, only an audit hook.
3. **Reject every bundled in-process plugin in production** — rejected as the
   fallback-safe but overly blunt option; it would break first-party plugins
   (e.g. `autodev/agent-coder`) that need no privileged capability and pose no
   more risk than core code. Kept as this ADR's explicit rollback plan below,
   since it is always available without further changes.

## Consequences

- **Positive:** Production installs no longer treat `in-process` manifests as
  equivalent to `subprocess`/`wasm` manifests; the policy matches the actual
  isolation the loader provides. The allowlist is auditable operator
  configuration, not scattered manifest claims.
- **Negative / trade-offs:** A privileged plugin that previously ran
  `in-process` must be repackaged behind `subprocess` or `wasm` to run in
  production, or the operator must accept it as core-equivalent trusted code
  with zero privileged capabilities.
- **Contract impact:** `PluginHost.__init__` gains two optional keyword
  arguments (`production_mode`, `trusted_in_process_plugins`) that default from
  `Settings`; existing callers that do not pass them are unaffected in local
  mode and gain the new production check without code changes.

## Rollback plan

Set `AUTODEV_TRUSTED_IN_PROCESS_PLUGINS=` (empty) in production. Every
`in-process` plugin is then rejected regardless of permissions, which is the
strict, always-safe fallback described in "Alternatives considered" above.
`subprocess`/`wasm` plugins are unaffected by this policy in every case.

## References

- `docs/architecture/v2_platform_reference.md` §16.1.4–§16.1.5.
- Story E11-S4.
