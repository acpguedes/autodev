# ADR-005: Determinism Boundary for Flow Checkpointing and Replay

- **Status:** Accepted
- **Date:** 2026-07-05
- **Authors:** AutoDev maintainers (via Claude Code)
- **Related epic:** E3 (story E3-S3)
- **Supersedes/Relates to:** ADR-004 (flow manifest and node types) — same
  flow contract; RFC-002 (flow.yaml proposal).

## Context

E3-S3 delivers crash recovery and deterministic replay for flow runs. Both
require agreeing on *what* the engine promises to reproduce: node handlers
call LLMs, tools, and agents, which are inherently non-deterministic and
side-effectful — re-executing them can never reproduce a past run bit-for-bit
(and may re-charge costs or re-fire side effects). A determinism boundary must
therefore separate what is **recorded** from what is **re-derived**.

## Decision

1. **Node outputs are recorded effects.** Every completed step persists its
   output in `flow_steps.output_json` and in the run-state checkpoint
   (`flow_runs.state_json`, under `nodes.<id>.output`). Replay and resume
   never re-execute a completed node: LLM/tool/agent calls happen at most
   once per successful attempt, at record time.
2. **Everything between recorded outputs is pure.** Input-binding rendering,
   predicate evaluation, and edge selection must be pure functions of
   persisted state (`flow.input` + recorded node outputs) and the versioned
   manifest — no clocks, randomness, environment reads, or hidden state. The
   shared routines live in `backend/flows/checkpoint.py`
   (`build_eval_state`, `select_next_node`) and are used identically by live
   execution and replay.
3. **The per-step state checkpoint is the recovery contract.** The engine
   persists cursor + node outputs + metrics after every step; `resume_run`
   continues an interrupted run from that checkpoint without re-executing
   completed steps, emitting `flow.run.resumed`.
4. **Replay is verification, not re-execution.** `replay_run` folds recorded
   step outputs in activation order, re-derives every binding and routing
   decision, and compares the derived node sequence (and final cursor) with
   the recorded trace, emitting `flow.run.replayed` with a
   `FlowReplayReport` (`deterministic`, recorded vs replayed sequences,
   divergence detail). A divergence means the trace was corrupted or the
   pure side changed (e.g. a different manifest/expression semantics), and
   is reported — fail closed on determinism, never silently repaired.
5. **Retries stay inside the boundary.** Failed attempts are recorded
   (per-attempt step rows and `run.step.failed` events) but only the
   successful attempt's output enters the checkpointed state; replay
   therefore ignores failed attempts. Backoff sleeping is a side effect of
   live execution only and is never replayed.
6. **Node outputs are canonicalized before they enter the boundary.** Every
   output is round-tripped through JSON (`canonical_output`) before it is
   recorded or folded into run state, so live routing always sees exactly
   what resume and replay will later read back from the store. An output
   that cannot survive the round trip fails the run closed (`node_failed`)
   instead of routing on a value replay could never rebuild.
7. **Resume reconciles the commit/checkpoint crash window.** `complete_step`
   and the state checkpoint are separate commits; a crash between them can
   leave the cursor node with a completed step whose output never reached
   `state.nodes` and whose `run.step.completed` event was never appended.
   `resume_run` detects this window from the recorded step and the event log
   alone (no re-execution), folds the output in, re-derives routing, and
   emits the missing event flagged `reconciled: true` before continuing —
   preserving "completed steps are never re-executed" across this crash
   window too.

## Alternatives considered

1. **Full re-execution replay (re-run handlers with cached seeds)** —
   rejected: LLM/tool calls cannot be seeded reliably, re-execution re-fires
   side effects and costs, and the platform already treats outputs as
   durable state (reference doc: durable state principle).
2. **Event-sourced replay from `flow_events` only** — rejected for now: the
   ordered event store doubles as an audit log, but steps already persist
   the authoritative inputs/outputs; deriving state from two sources would
   invite drift. Events remain the audit trail; steps are the replay source.
3. **Byte-level determinism (hash the whole state per step)** — deferred:
   sequence + binding + final-cursor comparison covers the routing decisions
   the story requires; content hashing can be layered on later without
   changing the boundary.

## Consequences

- **Positive:** crash recovery and replay need no cooperation from node
  handlers; plugins keep writing ordinary handlers. Replay is cheap (pure
  computation, no I/O beyond reading the trace) and safe to run on any
  terminal run, satisfying the "determinism guaranteed from the trace" NFR.
- **Negative / trade-offs:** replay verifies decisions, not node-internal
  behavior — a handler that returns different output for the same input is
  outside the boundary by design. Expression-language or routing changes
  between versions can make old traces report divergence; replay always
  resolves the manifest at the run's recorded version to minimize this.
- **Contract impact:** two new lifecycle events (`flow.run.resumed`,
  `flow.run.replayed`); no schema migrations (existing tables carry all
  required data).

## Rollback plan

`resume_run`/`replay_run` are additive engine APIs over existing persisted
data; rolling back is removing them (and `backend/flows/checkpoint.py`)
without any data migration. Checkpointing itself predates this story
(E3-S2 state persistence) and is unaffected.

## References

- `docs/flows/engine.md` (Checkpointing, retries, and replay);
  `docs/v2_platform/phases/e3_orchestration_engine.md` (E3-S3);
  `docs/architecture/v2_platform_reference.md` (durable state, fail closed).
