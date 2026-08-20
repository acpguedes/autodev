# E32 — Isolated Execution Environment (Beta cut)

**Wave:** v2.0-beta — "full platform in controlled production".
**Status:** Done · **Stories:** 4/4 complete (E32-S1..S4, 2026-08-18)
**Depends on:** E14-S4 (governed sandbox runners contract), E0 (MinIO
artifacts), E11 (audit sink, additive)
**Enables:** E28 (v2.2 tiered isolation & machine snapshots build on this
contract), E12 (contract tests for the isolation extension point), the
v2.0-beta gate on isolated real execution
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.9
(v2.0-beta), §2.5; `docs/v2_platform/beta_gap_analysis.md`; ADR-013
(accepted)

## Objective

Deliver the **Beta cut** of the isolated execution environment: a single,
well-defined **execution-environment abstraction** behind which the
isolation backend is pluggable, with a **fail-closed** filesystem/network
policy and a governed lifecycle (provision → execute → collect evidence →
teardown). The Beta cut deliberately does **not** decide the final
isolation technology (container vs bubblewrap vs gVisor/microVM) — that
decision is documented in **ADR-013** with options, trade-offs and a
recommendation, and remains implementable behind the abstraction. E28
(v2.2) later upgrades the backend (microVM class, machine snapshots)
without changing the contract.

## Key result

A real task from E14 executes end to end inside an isolated environment
whose isolation backend is selected by configuration (not by callers),
with fail-closed defaults (no network, no host filesystem beyond the
workspace mount, no ambient credentials), and every execution record names
its environment profile for audit.

## Relation to E14 and E28 (Beta cut boundary)

- **E14** owns *what* runs (ExecutionTask/ExecutionAction, permission and
  approval policy, governed autonomy) and the runner contract (E14-S4).
- **E32** owns *where* it runs in Beta: the environment abstraction,
  fail-closed policy, lifecycle and audit — one backend class, pluggable.
- **E28** (v2.2) extends E32's abstraction with tiered isolation
  (`trusted`/`untrusted`), microVM-class backends and machine snapshots.
  E28-S2 consumes the E32 contract; it must not fork it.

## Stories

### E32-S1 — Execution-environment abstraction & backend selection — **Complete** (2026-08-18)

`backend/environments/contracts.py` (`EnvironmentProfile`, `EnvironmentBackend`
protocol), `backends.py` (`HardenedContainerBackend`, `UnavailableBackend`),
`registry.py` (`resolve_backend`, configuration-only selection).
`CompositeActionRunner.bind_environment` (`backend/execution/runner.py`)
consumes the contract; `ExecutionResult` gains an additive `environment`
field. ADR-013 accepted (hardened container default; `UnavailableBackend`
proves the second implementation).

Subtasks:
- `E32-S1-T1`: environment contract — a declared environment profile
  (base image/rootfs, workspace mount, resource limits, network policy,
  env allowlist) consumed by the E14-S4 runner contract; backends
  implement the same interface.
- `E32-S1-T2`: backend selection by configuration/policy only — callers
  never name a backend; unknown/unset configuration resolves to the most
  restrictive available backend (fail-closed).
- `E32-S1-T3`: ADR-013 lifecycle — options (container hardening,
  bubblewrap, gVisor, microVM), trade-offs, recommendation and pending
  decision recorded; abstraction validated against at least the default
  backend so the decision does not block Beta.

| Criterion | Detail |
| --- | --- |
| Functional | The same ExecutionTask runs unchanged when the backend is swapped in configuration; callers cannot select a backend; execution records name the resolved profile |
| Non-functional | Backend swap requires no changes outside the environment layer; overhead of the default backend measured and documented |
| DoR (specific) | ADR-013 filed (may be `Proposed`); E14-S4 runner contract reviewed |
| DoD (specific) | Contract tests green for the default backend; `docs/environments/beta_isolation.md` |
| Dependencies | E14-S4 |

### E32-S2 — Fail-closed network & filesystem policy — **Complete** (2026-08-18)

`backend/environments/policy.py` (`evaluate_network_provisioning`,
`evaluate_filesystem_access`); denials are durably recorded and emitted as
`environment.access.allowed`/`.denied` by `EnvironmentManager.evaluate_filesystem`.
Scope boundary: Beta enforces default-deny egress mechanically; a declared
per-profile allowlist is not yet mechanically enforceable and therefore
fails closed at provisioning rather than being silently granted or
ignored (see `docs/environments/beta_isolation.md`).

Subtasks:
- `E32-S2-T1`: default-deny network egress for task execution; explicit
  per-profile allowlist (e.g., package registries) declared in the
  environment profile and surfaced in the approval flow (E14-S2).
- `E32-S2-T2`: filesystem scope — workspace mount only; host paths,
  sockets and devices denied by default; read-only base layers.
- `E32-S2-T3`: policy violations produce typed, audited denials (not
  silent failures); violations visible in run timeline events.

| Criterion | Detail |
| --- | --- |
| Functional | A task attempting non-allowlisted egress or host-path access fails closed with a typed denial recorded in the run timeline |
| Non-functional | Policy evaluation adds negligible latency to environment start; defaults documented for self-hosters |
| DoR (specific) | E32-S1 contract available |
| DoD (specific) | Egress-deny and host-path-deny tests; policy section in `docs/environments/beta_isolation.md` |
| Dependencies | E32-S1, E14-S2 (approval surface, additive) |

### E32-S3 — Environment lifecycle & workspace provisioning — **Complete** (2026-08-18)

`backend/environments/manager.py` (`EnvironmentManager.provision`/
`collect_artifacts`/`teardown`/`reap_orphans`), `store.py`
(`EnvironmentStore`, durable lifecycle records). Wired into
`OrchestratorService._process_tasks`: one environment per dispatch batch,
provisioned before and torn down (collecting artifacts) after — including
on an approval-mode pause, so a paused run's environment is reaped by TTL
rather than held indefinitely; resume provisions a fresh one. Concurrency
bounded per tenant by `AUTODEV_ENVIRONMENT_MAX_CONCURRENT`. Scope
boundary: workspace provisioning binds to the orchestrator's existing
`project_root` rather than a fresh ref-pinned checkout (see
`docs/environments/beta_isolation.md`) — deferred alongside E28-S1's
snapshot mechanism.

Subtasks:
- `E32-S3-T1`: lifecycle — provision → execute → collect artifacts/diffs →
  teardown; orphan reaping with TTL; concurrent environments per run
  bounded by quota (E11).
- `E32-S3-T2`: workspace provisioning — repository checkout/mount into the
  environment with deterministic state (ref + dirty-state policy);
  provisioning steps recorded for later snapshot reuse (E28-S1 hook, not
  implemented here).
- `E32-S3-T3`: artifact egress — only declared outputs (diff, logs,
  artifacts) leave the environment, via the artifact store (MinIO).

| Criterion | Detail |
| --- | --- |
| Functional | A full E14 plan→patch→validate flow runs with environments provisioned and torn down per lifecycle; orphans are reaped; outputs egress only through the artifact store |
| Non-functional | Environment start p95 measured and documented (baseline for E28-S1 snapshot savings) |
| DoR (specific) | E32-S1; E14-S1 execution flow available |
| DoD (specific) | Lifecycle + orphan-reaping tests; provisioning baseline recorded in `docs/environments/beta_isolation.md` |
| Dependencies | E32-S1, E14-S1, E0-S7 (artifacts) |

### E32-S4 — Isolation audit & evidence — **Complete** (2026-08-18)

`ExecutionResult.environment` (additive field: `environmentId`,
`backendKind`, `profileHash`) on every action result;
`EnvironmentManager.list_for_run`/`.list_decisions_for_run` reconstruct a
run's environment/policy history from durable records.
`environment.instance.provisioned`/`environment.access.*`/
`environment.instance.retired` events (catalog 42 → 46 types).

Subtasks:
- `E32-S4-T1`: every execution record carries the resolved environment
  profile, backend class and policy decisions (allow/deny events) —
  consumed by E11 audit.
- `E32-S4-T2`: evidence — environment configuration hash included in run
  evidence so gates can assert "ran isolated" mechanically.
- `E32-S4-T3`: Beta gate wiring — the v2.0-beta gate criterion "isolated
  execution fail-closed" is asserted from these records, not from
  configuration claims.

| Criterion | Detail |
| --- | --- |
| Functional | An auditor can reconstruct, from run records alone, which backend/profile every execution used and which policy denials occurred |
| Non-functional | Audit fields additive to existing E11 schemas (no breaking changes) |
| DoR (specific) | E32-S2, E32-S3 landed; E11 audit sink available |
| DoD (specific) | Audit-field and gate-assertion tests; `docs/v2_platform/progress.md` updated |
| Dependencies | E32-S2, E32-S3, E11 |

## Contracts & decisions

- **ADR-013 — Isolation backend for Beta** (accepted 2026-08-18): hardened
  container is the Beta default, behind the backend-agnostic
  `EnvironmentBackend` protocol; `UnavailableBackend` proves the second
  implementation. Escalation to a microVM-class backend is E28 (v2.2)
  scope, consuming this contract unchanged.
- Extension point `execution_environment`: the `EnvironmentBackend`
  protocol is code-level backend-agnostic, proven by two implementations
  and covered by unit contract tests (`backend/tests/unit/environments/`).
  It is **not** wired into the plugin SDK's `ExtensionPointKind` catalog —
  that (letting a third-party plugin ship an isolation backend) is
  deferred to E28 alongside the microVM backend it would first be
  exercised against; see `docs/environments/beta_isolation.md`.

## DoR / DoD

- **DoR:** E14-S4 contract reviewed; ADR-013 filed; gap analysis subsection
  (`beta_gap_analysis.md`) approved.
- **DoD:** all story DoDs met; `docs/environments/beta_isolation.md`
  published; ADR-013 accepted; v2.0-beta gate criteria (§18.9) reference
  E32 evidence (`docs/v2_platform/progress.md`); no push/PR without
  explicit authorization.
