# E32 — Isolated Execution Environment (Beta cut)

**Wave:** v2.0-beta — "plataforma completa em produção controlada".
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E14-S4 (governed sandbox runners contract), E0 (MinIO
artifacts), E11 (audit sink, additive)
**Enables:** E28 (v2.2 tiered isolation & machine snapshots build on this
contract), E12 (contract tests for the isolation extension point), the
v2.0-beta gate on isolated real execution
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.9
(v2.0-beta), §2.5; `docs/v2_platform/beta_gap_analysis.md`; ADR-013
(pending)

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

### E32-S1 — Execution-environment abstraction & backend selection

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

### E32-S2 — Fail-closed network & filesystem policy

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

### E32-S3 — Environment lifecycle & workspace provisioning

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

### E32-S4 — Isolation audit & evidence

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

- **ADR-013 — Isolation backend for Beta** (pending): container hardening
  vs bubblewrap vs gVisor vs microVM. Options, trade-offs and
  recommendation documented; decision does not block E32-S1..S4 because
  the abstraction is backend-agnostic. Escalation of the backend is E28
  (v2.2) scope.
- Extension point `execution_environment` gets a mandatory contract test
  (E12).

## DoR / DoD

- **DoR:** E14-S4 contract reviewed; ADR-013 filed; gap analysis subsection
  (`beta_gap_analysis.md`) approved.
- **DoD:** all story DoDs; `docs/environments/beta_isolation.md` published;
  v2.0-beta gate criteria (§18.9) reference E32 evidence; no push/PR
  without explicit authorization.
