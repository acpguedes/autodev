# ADR-013 — Isolation Backend for Beta Execution Environments

- **Status:** Accepted
- **Date:** 2026-07-17 (proposed) / 2026-08-18 (accepted)
- **Epic:** E32
- **Stories:** E32-S1..S4 (implemented behind the abstraction)

## Context

The v2.0-beta gate now requires real task execution inside a fail-closed
isolated environment (`v2_platform_reference.md` §18.9, criterion 10). The
strong tiered-isolation layer (microVM class, machine snapshots) is E28
(v2.2). Beta needs one isolation backend today, chosen deliberately, behind
the E32 execution-environment abstraction so E28 can upgrade it without
contract changes.

## Options

| Option | Pros | Cons |
| --- | --- | --- |
| Hardened container (Docker/OCI: no-new-privileges, cap-drop, seccomp, read-only rootfs, default-deny egress) | Already the SandboxRunner substrate; works on WSL2/macOS/Linux; lowest delivery risk | Shared kernel; weakest boundary of the four |
| bubblewrap | No daemon; unprivileged namespaces; light | Linux-only; no WSL2/macOS parity; weaker story for network policy; new substrate to operate |
| gVisor (runsc) | Syscall interception, materially stronger than plain containers; drop-in OCI runtime | Linux-only; syscall compat gaps; performance overhead; not available where KVM/host constraints bite |
| microVM (Firecracker/Kata) | Strongest boundary; the E28 target class | Requires KVM (excludes default WSL2/macOS dev hosts); heaviest operational lift; premature for Beta |

## Decision

Hardened container (`backend.environments.backends.HardenedContainerBackend`,
built on the existing `backend.validation.sandbox.SandboxRunner`) is the
Beta default backend behind the E32 abstraction. The backend interface is
proven backend-agnostic by a second implementation,
`UnavailableBackend` (the fail-closed sentinel selected for an unset/
unrecognized backend configuration — see
`docs/environments/beta_isolation.md`). microVM class arrives as E28-S2
(`untrusted`) in v2.2, consuming this same `EnvironmentBackend` contract
unchanged. gVisor remains documented as the self-host option where
stronger isolation is required before v2.2.

## Consequences

- E32-S1 kept callers backend-agnostic (`backend.environments.registry.resolve_backend`
  is the single selection point; `ExecutionAction`/`ExecutionResult` are
  unchanged when the backend is swapped in configuration).
- E32-S2's fail-closed network/filesystem policy is backend-independent
  and implemented (`backend/environments/policy.py`).
- E28 must consume `backend.environments.contracts.EnvironmentBackend`
  unchanged when it adds the microVM-class backend; it must not fork the
  contract.
