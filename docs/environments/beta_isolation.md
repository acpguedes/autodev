# Isolated Execution Environments (Beta cut) — E32

Canonical source: `docs/architecture/v2_platform_reference.md` §18.9 (v2.0-beta),
`docs/v2_platform/phases/e32_isolated_execution_beta.md`,
`docs/v2_platform/decisions/ADR-013-beta-isolation-backend.md`.

## What this delivers

E32 owns *where* a real task from E14 runs: a backend-agnostic execution-
environment abstraction with a fail-closed network/filesystem policy and a
governed provision → execute → collect → teardown lifecycle. E14 continues
to own *what* runs (`ExecutionTask`/`ExecutionAction`, permission and
approval policy).

Code: `backend/environments/`.

- `contracts.py` — `EnvironmentProfile`, `NetworkPolicy`, `FilesystemPolicy`,
  the `EnvironmentBackend` protocol, `EnvironmentHandle`.
- `backends.py` — `HardenedContainerBackend` (Beta default, ADR-013) and
  `UnavailableBackend` (fail-closed sentinel).
- `registry.py` — `resolve_backend`: configuration-only backend selection.
- `policy.py` — pure network/filesystem policy evaluation functions.
- `store.py` — durable SQLite-backed lifecycle records and policy-decision
  audit rows (`execution_environments`, `execution_environment_decisions`).
- `manager.py` — `EnvironmentManager`, tying the above together: admission
  (concurrency ceiling), provisioning, audited policy checks, artifact
  egress, teardown, and orphan reaping.

Integration: `backend.execution.runner.CompositeActionRunner.bind_environment`
scopes action dispatch to a provisioned environment (E32-S1-T1);
`OrchestratorService._process_tasks` provisions one environment per
dispatch batch and tears it down (collecting artifacts first) once that
batch completes or pauses (E32-S3).

## Backend selection (E32-S1-T2)

Callers never choose a backend. `AUTODEV_EXECUTION_ENVIRONMENT_BACKEND`
resolves it:

| Value | Resolves to |
| --- | --- |
| unset / empty | `hardened_container` (the Beta default) |
| `hardened_container` | `HardenedContainerBackend` |
| `unavailable` | `UnavailableBackend` (deny-all) |
| anything else (typo) | `UnavailableBackend` — fails closed rather than silently picking a backend the operator did not ask for |

## ADR-013 — accepted for Beta

**Decision:** hardened container (`HardenedContainerBackend`, built on the
existing `backend.validation.sandbox.SandboxRunner`) is the Beta default
isolation backend. `UnavailableBackend` is the second implementation behind
the same `EnvironmentBackend` protocol, proving the abstraction is
backend-agnostic per ADR-013's own recommendation. gVisor/bubblewrap/microVM
remain documented options for a stronger boundary; microVM-class tiered
isolation is E28 (v2.2) scope and must consume this contract unchanged.

## Fail-closed network/filesystem policy (E32-S2)

- **Filesystem:** `FilesystemPolicy.workspace_only=True` (the default) —
  every file/patch/command action's target path is checked against the
  environment's workspace mount before dispatch
  (`evaluate_filesystem_access`); an escape is denied and durably audited,
  never silently attempted.
- **Network:** `NetworkPolicy.deny_all=True` (the default) maps to Docker
  `--network=none` (already the `SandboxRunner` hardened default).
  **Scope boundary:** Beta's `HardenedContainerBackend` has no egress
  proxy or DNS-level allowlist (that is E28 scope). A profile that
  declares `deny_all=False` with a non-empty `allowlist` is therefore
  *unenforceable as declared* — `evaluate_network_provisioning` denies
  provisioning outright rather than silently granting full network access
  (broader than promised) or silently ignoring the allowlist (narrower
  than promised). An explicit `deny_all=False` with an *empty* allowlist
  (a deliberate, documented full-open profile) is provisionable.
- Whether sandboxed execution runs at all remains governed by
  `AUTODEV_ENABLE_SANDBOX`/`AUTODEV_SANDBOX_ALLOW_LOCAL` (E0/E14's existing
  fail-closed defaults) — an environment binding scopes network policy and
  the workspace root; it does not itself force execution on for a
  deployment that has not opted in.

## Lifecycle & workspace provisioning (E32-S3)

- **Provision:** `EnvironmentManager.provision()` reaps the tenant's
  orphaned environments first (lazy sweep, mirroring
  `backend.execution.decisions.DecisionService.expire_due`), admits the
  request against `AUTODEV_ENVIRONMENT_MAX_CONCURRENT` (default 8,
  per-tenant), then delegates to the resolved backend. A capacity or
  backend failure denies every task in the current dispatch batch
  (`EnvironmentManager` never falls back to unisolated execution).
- **Execute:** actions dispatch through `CompositeActionRunner.bind_environment`,
  scoped to the provisioned workspace and network policy.
- **Collect:** `collect_artifacts()` egresses only each action's declared
  outputs (stdout/stderr as a `LOG` artifact, a unified diff as a
  `RUN_EXPORT` artifact) via the artifact store (MinIO/local, E0/E8) —
  nothing else is read back from the workspace mount. Egress is
  best-effort: a store failure (e.g. an unwritable `AUTODEV_ARTIFACT_DIR`
  in a local/dev deployment) is logged and skipped rather than failing the
  run — evidence durability does not gate task execution.
- **Teardown:** `teardown()` marks the environment's record terminal and
  emits `environment.instance.retired`. Orphan reaping
  (`AUTODEV_ENVIRONMENT_TTL_SECONDS`, default 1800s) marks an environment
  `orphaned` if it is never torn down (e.g. a long-paused approval-mode
  run's environment expires while awaiting a decision; resume provisions a
  fresh one).

## Audit & evidence (E32-S4)

Every `ExecutionResult` (`backend.execution.contracts.ExecutionResult`)
carries an additive `environment` field: `{"environmentId", "backendKind",
"profileHash"}` when the action ran inside a bound environment, `{}`
otherwise (unbound construction, fully backward compatible with E14).

`EnvironmentManager.list_for_run(run_id)` and `.list_decisions_for_run(run_id)`
let an auditor reconstruct, from durable records alone, which
backend/profile every environment in a run used and which policy denials
occurred — the v2.0-beta gate's "isolated execution fail-closed" criterion
is asserted from these records, not from configuration claims.

Events (append-only, `backend/events/catalog.py`):

- `environment.instance.provisioned` — `environmentId`, `backendKind`, `profileId`, `profileHash`.
- `environment.access.allowed` / `environment.access.denied` — `environmentId`, `category` (`network`/`filesystem`), `target`, `reason`.
- `environment.instance.retired` — `environmentId`, `reason` (`completed`/`failed`/`orphan_reaped`).

## Scope boundary (Beta cut)

- No plugin-facing `execution_environment` extension point yet: the
  `EnvironmentBackend` protocol is code-level backend-agnostic (proven by
  two implementations), but is not wired into the plugin SDK's
  `ExtensionPointKind` catalog/contract-test harness
  (`backend/sdk/contracts.py`, `backend/tests/contract/`). That wiring —
  letting a third-party plugin ship an isolation backend — is deferred to
  E28 alongside the microVM-class backend it would first be exercised
  against; doing it now would add SDK/permission surface with no second
  real consumer to validate it against.
- Per-profile CPU/memory/pids overrides are captured in
  `EnvironmentProfile` and hashed into every execution record, but Beta's
  `HardenedContainerBackend` does not yet vary the container's resource
  flags beyond `SandboxRunner`'s existing hardened defaults (512m/1cpu/256
  pids) — widening that is E28 scope, not a Beta contract change.
- Environment start latency (a baseline for E28-S1's snapshot-reuse
  savings) is not yet benchmarked; this backend reuses `SandboxRunner`'s
  existing per-command container start, already exercised by E14-S4's own
  performance baseline.
- **Workspace provisioning binds to the orchestrator's existing
  `project_root`**, not a fresh per-environment checkout: the platform has
  no VCS checkout/worktree-provisioning mechanism anywhere yet (this is
  not an E32-specific gap), so a ref-pinned, dirty-state-aware clone per
  environment and "provisioning steps recorded for snapshot reuse" are
  deferred alongside E28-S1's machine-snapshot mechanism, which is the
  actual consumer of that hook. Every action's filesystem access is still
  checked against the workspace mount (E32-S2) regardless.
