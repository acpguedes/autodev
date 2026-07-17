# E3 — Orchestration Engine (Flow Engine)

**Wave:** Split — graph/checkpointing/human-in-the-loop stories targeted Alpha;
E3-S6 (visual editor) completed in Beta alongside E10, delivered via E10-S3 +
E17-S6.
**Status:** Complete · **Stories:** 6/6 complete (S1-S5 Alpha; S6 via E10-S3 + E17-S6)
**Depends on:** E0, E2
**Enables:** E10-S3; consumes E8-S2 (checkpointing/events)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.6 (E3), §18.8, §18.9

## Objective

Make **flow-as-configuration** real: a versioned declarative graph, checkpointing,
retries, **human-in-the-loop**, and a visual editor.

## Key result

A `flow.yaml` defines a graph of nodes (agent/skill/tool/conditional/human/sub-flow/
map-reduce) that the Orchestration Engine executes with durable, resumable, observable
state.

## Stories

### E3-S1 — `flow.yaml` specification (declarative graph)

Subtasks:
- `E3-S1-T1`: node and conditional-edge schema.
- `E3-S1-T2`: graph validation (cycles, IO types between nodes).
- `E3-S1-T3`: flow versioning.

| Criterion | Detail |
| --- | --- |
| Functional | A flow with every node type validates; a conditional edge evaluates a predicate over state; an invalid graph is rejected |
| Non-functional | Flow validation < 100 ms; schema contract tests |
| DoR (specific) | Canonical node types defined (reference doc §3) |
| DoD (specific) | Schema in the SDK; `docs/flows/spec.md` |
| Dependencies | E1-S1 |

### E3-S2 — Graph execution with durable state (Run/Step)

Subtasks:
- `E3-S2-T1`: graph executor.
- `E3-S2-T2`: Run/Step persistence in the State Store.
- `E3-S2-T3`: triggers (message/webhook/cron/Event Bus).

| Criterion | Detail |
| --- | --- |
| Functional | A run executes the graph in the correct order; each step persists status/attempts; a trigger starts a run |
| Non-functional | >= 100 concurrent runs per worker node; run streaming starts < 1 s |
| DoR (specific) | Run/Step model (E0-S2) available |
| DoD (specific) | Concurrency test; `flow.run.started`/`run.step.completed` events emitted |
| Dependencies | E3-S1, E0-S2, E2-S3 |

### E3-S3 — Checkpointing, retries, and deterministic replay

Subtasks:
- `E3-S3-T1`: per-step checkpoints.
- `E3-S3-T2`: retry/backoff policy.
- `E3-S3-T3`: replay from persisted state.

| Criterion | Detail |
| --- | --- |
| Functional | An interrupted run resumes from the last checkpoint; retry honors policy; replay reproduces decisions |
| Non-functional | Determinism guaranteed from the trace; checkpoint overhead < 10% |
| DoR (specific) | Determinism boundary agreed |
| DoD (specific) | Crash-recovery test and identical-replay test |
| Dependencies | E3-S2 |

### E3-S4 — Human-in-the-loop

Subtasks:
- `E3-S4-T1`: pause/approval node.
- `E3-S4-T2`: API to resume with a decision/edit.
- `E3-S4-T3`: timeout/expiration.

| Criterion | Detail |
| --- | --- |
| Functional | A flow pauses at a human node and resumes after a decision; human edits alter state; timeout triggers an alternate route |
| Non-functional | Pause state durable (survives restart); RBAC applied to the decision |
| DoR (specific) | Human decision contract defined |
| DoD (specific) | Pause/resume test and timeout test; approval event |
| Dependencies | E3-S2, E0-S4 |

### E3-S5 — Composite nodes: sub-flow and map/reduce

Subtasks:
- `E3-S5-T1`: nested sub-flow.
- `E3-S5-T2`: parallel map/reduce.
- `E3-S5-T3`: result aggregation and budget propagation.

| Criterion | Detail |
| --- | --- |
| Functional | A sub-flow executes and returns to the parent; map fans out N branches and reduce aggregates; parent budget limits the children |
| Non-functional | Parallelism scales horizontally; aggregated budget fails closed |
| DoR (specific) | Budget-propagation semantics defined |
| DoD (specific) | Map/reduce and sub-flow tests; hierarchical trace |
| Dependencies | E3-S2, E2-S3 |

### E3-S6 — Visual flow editor (base)

Subtasks:
- `E3-S6-T1`: render the graph from `flow.yaml`.
- `E3-S6-T2`: bidirectional editing (visual <-> YAML).
- `E3-S6-T3`: inline validation.

| Criterion | Detail |
| --- | --- |
| Functional | Editing on the canvas updates `flow.yaml` and vice versa; validation errors appear inline |
| Non-functional | WCAG 2.2 AA; 100% keyboard editing; rendering a 50-node graph < 500 ms |
| DoR (specific) | Base design tokens/components available (depends on E10) |
| DoD (specific) | Visual<->YAML round-trip test; a11y audit |
| Dependencies | E3-S1, E10 (base Design System) |

**Status: Done** — delivered via **E10-S3** (deterministic `flow.yaml`↔manifest
round-trip in `frontend/lib/flow/yaml.ts`, covered by `frontend/lib/flow/yaml.test.ts`)
and **E17-S6** (three-column editor `FlowCanvas`/`FlowPalette`/`NodeInspector`,
inline validation `frontend/lib/flow/validate.ts` + `validate.test.ts`, keyboard
editing + storybook-axe a11y checks, and the `frontend/e2e/flow-builder.spec.ts`
e2e). T1 render, T2 bidirectional edit, and T3 inline validation are all met.

## v1 precursor / starting point

- `backend/orchestrator/service.py` runs a LangGraph-based **linear, hardcoded**
  pipeline (Navigator -> Analyzer -> Architect -> Coder -> DevOps -> Validator ->
  Responder) — this is the closest existing analogue to the Orchestration Engine but
  has no declarative `flow.yaml`, no checkpointing/replay, and no human-in-the-loop
  node.
- Optional dynamic routing already exists behind `AUTODEV_DYNAMIC_ORCH=1`
  (`backend/orchestrator/routing.py`, `backend/orchestrator/graphs.py`,
  `POST /chat/dynamic`) and `SupervisorPolicy` is defined but not wired into
  execution — see `docs/implementation/dynamic_orchestration.md`. This is real
  precedent for E3-S2's executor and E3-S4/E5's routing, but it is opt-in, linear
  per selected route, and not durable/replayable.
- There is no visual flow editor today; E3-S6 explicitly depends on E10's base Design
  System and can stay minimal through Alpha.

## Epic exit checklist

- [x] All 6 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above (S6 via E10-S3 + E17-S6).
- [x] Contract tests green for the flow schema and node-type extension points
      (flow suite 38/38).
- [x] `docs/v2_platform/progress.md` updated.
- [x] Alpha exit criterion "a declarative flow executes an agent-plugin end-to-end with
      durable state and event-store replay" satisfied (E3-S1..S4); E3-S6 completed in
      Beta alongside E10.
