# ADR-013 — Isolation Backend for Beta Execution Environments

- **Status:** Proposed (decision pending — do not resolve silently)
- **Date:** 2026-07-17
- **Epic:** E32
- **Stories:** E32-S1..S4 (implementable behind the abstraction while pending)
- **Decide by:** before E32-S2 starts

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

## Recommendation (not a decision)

Hardened container as the Beta default backend behind the E32 abstraction,
with the backend interface proven by a second implementation stub; microVM
class arrives as E28-S2 (`untrusted`) in v2.2. gVisor documented as the
self-host option where stronger isolation is required before v2.2.

## Consequences (of the pending state)

- E32-S1 must keep callers backend-agnostic so any option remains viable.
- E32-S2 (fail-closed policy) is backend-independent and proceeds.
- The decision owner and milestone are tracked in the E35-S3 open-decisions
  register; resolving this ADR updates §18.9 evidence expectations, not the
  E32 contract.
