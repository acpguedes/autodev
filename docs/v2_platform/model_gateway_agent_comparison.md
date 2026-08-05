# AutoDev Internal Agents vs. Traycer: Evidence Matrix

Supporting evidence for [ADR-016](decisions/ADR-016-model-gateway.md), specifically the
decision that **external coding agents are not model providers** and belong behind a
future `CodingAgentHarness` abstraction rather than behind `ModelProvider`.

This document exists because "agent" means two different things in the two systems.
Conflating them would have pushed external coding-agent lifecycle concerns (process
spawning, PTY handover, workspace isolation, approval prompts) into the model gateway,
where they do not belong.

## Scope and honesty rules

Every claim below is classified as exactly one of:

| Class | Meaning |
| --- | --- |
| **code-confirmed** | The implementation was read in the inspected repository; a path is cited. |
| **documentation-only** | Stated in that repository's own README/docs; the implementation was not found there. |
| **unverifiable product claim** | Asserted publicly, but the implementing code is not in the inspected repository. |

Claims are deliberately conservative: where the implementing code is not public, the
claim is recorded as unverifiable rather than assumed true **or** assumed false.

## Evidence provenance

- Repository: `https://github.com/traycerai/traycer.git`
- Immutable commit inspected: `8f21d506f9945e409f4cd72f32c71e8810a4d236`
- License: `LICENSE` at the repository root — **MIT License**, Copyright (c) 2026 Traycer AI
- No Traycer source code was copied into AutoDev. Only architectural concepts and
  citations were used.

**Material scope limitation, stated by that repository itself** (`AGENTS.md`): the
open-source portion is the *clients, CLI, and protocol*. The Traycer Host and cloud
backends are not in the repository — the CLI provisions a signed host from GitHub
Releases. The actual execution engine (harness spawning, scheduling, persistence
read/write, model-call orchestration) is therefore **closed-source**, and most
behavioral guarantees are verifiable only as wire contracts, not as implementations.

## Comparison matrix

| Dimension | AutoDev internal agent | Traycer | Class | Citation (Traycer) |
| --- | --- | --- | --- | --- |
| Agent definition | Declarative Agent Manifest interpreted by an in-repo `AgentRuntime` | A durable *session* bound to a `harnessId` (Claude Code, Codex, OpenCode, Cursor, …) | code-confirmed (contract) | `protocol/src/host/agent/gui/agent-runtime.ts:139-145,192-232`; `protocol/src/host/agent/shared.ts:13-40` |
| Execution boundary | In-process; runtime calls the model gateway directly | External process by design; Host drives an external CLI/SDK, or hands the user's PTY to it | code-confirmed (contract only) | `protocol/src/host/agent/shared.ts:16-24` |
| Model / provider selection | Provider-neutral gateway resolves provider + model from manifest with deterministic precedence | No Traycer-owned model abstraction; `model` is a concrete slug "resolved upstream", validated by each adapter at its own SDK boundary | code-confirmed (contract) | `protocol/src/host/agent/gui/agent-runtime.ts:192-215`, `:158-172` |
| Provider-neutral contract | Single capability + error vocabulary across providers | 18 enumerated provider IDs with structurally different per-provider rate-limit/response shapes — a dispatch union, not a normalized contract | code-confirmed | `protocol/src/host/provider-ids.ts:3-22`; `protocol/src/agent/agent-profile-format.ts:83-174` |
| Agent-to-Agent | Explicit non-goal for E2-S6 | Host-local text injection (`[traycer:agent-message]`) with a `responseId` thread convention — **not** the open Agent2Agent standard | code-confirmed (mechanism); absence-confirmed (no `agent2agent` match anywhere in the repo) | `protocol/src/agent/a2a-message-format.ts:1-85` |
| Parallel execution | Explicit non-goal for E2-S6 | Multi-agent addressing contract exists; the scheduler and concurrency control are in the closed Host | documentation-only (the parallelism claim); code-confirmed (addressing only) | `protocol/src/host/agent/contracts.ts:56-90`, `303-420` |
| Durable memory / session | Durable state store (PostgreSQL / Redis / pgvector direction) | Versioned on-disk + Yjs (CRDT) "epic" records; cross-model continuity is a `contextPrelude` string re-injected into the new harness prompt | code-confirmed (schema); documentation-only (fidelity of "seamless" continuity) | `protocol/src/persistence/registry.ts:1-30`; `agent-runtime.ts:209` |
| Approvals / permissions | Manifest-declared policy enforced by `AgentRuntime` | `permissionMode` (`supervised｜auto_accept_edits｜full_access`), tool-call approve/deny, and a plan-approval state machine | code-confirmed (contract) | `agent-runtime.ts:118-127`, `:143-155`, `:252-259` |
| Workspace isolation | Docker sandboxing direction | Git-worktree binding per chat/terminal agent, plus a client-side worktree-health classifier; creation/enforcement is in the closed Host | code-confirmed (contract + classifier) | `protocol/src/host/worktree-schemas.ts:1-80`; `clients/shared/worktree/classify-worktree.ts:1-56` |

## Claims that could not be verified

These are recorded as **unverifiable product claims** — not as refuted claims:

- Parallel-agent guarantees (isolation, resource limits, race handling): no scheduler code is public.
- "Unified context seamlessly shared across all providers": the only public mechanism is a single `contextPrelude` string; how the Host builds it, and how faithfully it substitutes for real shared context, is closed-source.
- Collaboration features (shareable boards, real-time co-editing, ticket assignment) and cross-device sync: no implementation found in the public clients beyond Yjs scaffolding.
- Any normalization/governance behavior equivalent to AutoDev's model gateway: Traycer has no public provider-neutral model contract, so this can be confirmed neither way.
- Whether the referenced A2A capability matrix is enforced anywhere: only the message-formatting layer is public.

## Why this matters for AutoDev

The two systems differ in **kind**, not in quality:

- AutoDev's model is *one owned runtime, one owned model contract, agents as manifests*. Model and provider selection is AutoDev's own concern, normalized behind `backend.llm` contracts.
- Traycer's model is *one owned orchestration and persistence protocol wrapped around many external, independently-versioned coding-agent processes*. Model selection is explicitly delegated to each harness's SDK.

Three consequences for E2-S6, in priority order:

1. **Do not model external coding agents as `ModelProvider`s.** They carry process, workspace, approval, and patch semantics that the model gateway has no vocabulary for. This is the concrete justification for ADR-016's `CodingAgentHarness` deferral.
2. **A provider-neutral contract is a real differentiator, and the cost is ours.** Because Traycer delegates model selection downward, it needs no capability/error normalization. AutoDev chose the opposite, so AutoDev must maintain the taxonomy — the trade-off ADR-016 already records.
3. **"Agent-to-Agent" claims need care in public docs.** The inspected implementation is host-local text injection, not the open Agent2Agent standard. AutoDev should not cite it as evidence that the open standard is in production use.

## Limitations of this comparison

- It reflects one immutable commit; Traycer may have changed since.
- The closed Host means the strongest behavioral claims on both sides of the "parallel execution" and "durable context" rows are not comparable on equal evidence.
- No performance or quality benchmarking was performed. Nothing here ranks the two systems.

## References

- [ADR-016](decisions/ADR-016-model-gateway.md) — the model gateway boundary decision this evidence supports.
- [E2 phase page](phases/e2_agent_framework.md) — E2-S6 scope and explicit non-goals.
