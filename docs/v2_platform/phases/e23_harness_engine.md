# E23 — Harness Engine & Loop Engineering

**Wave:** v2.1 — Spec & Harness (after E20; S2+ additionally gated on E14
(real execution) and E22 (verification gates as reward signal)).
**Status:** Not started · **Stories:** 0/5 complete
**Depends on:** E3 (Flow Engine), E4 (reasoning strategies), E14 (real
execution + sandbox), E20 (specs), E22 (verification gates)
**Enables:** E24-S5 (harness composer UI), E25-S2 (Extension Studio runs
extension builds as harness runs)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §22.6,
§18.7.15; RFC-007

## Objective

Make the agent harness a **named, governed, reusable unit**: a `harness.yaml`
contract that binds a spec + a flow + a loop policy + verification gates +
budgets into one artifact with typed result states, pluggable loop policies
(evaluator-optimizer, fresh-context re-hydration, circuit breaker, heartbeat),
durable loop state that survives sessions, parallel isolation with task
claiming and a candidate-race pattern, and first-class observability through
`/v2/harnesses`.

**Harness engineering** is the discipline of designing the outer runtime
scaffold around an agent: the artifact that defines the objective, admissible
actions, state, gates, evidence, budgets, stop states, replay surface and
handoff boundaries. **Looping engineering** is the discipline of deciding when
and how that scaffold iterates: progress signals, recovery choices, stagnation
detection, fresh-context rehydration, candidate forks, human escalation and
cost-aware termination. E23 is the v2.1 foundation for both; E37 later hardens
them with a pattern catalog, `PhaseHandoff` context quarantine, recovery
taxonomy and replay debugger requirements without changing the E23 boundary.

## Key result

An operator (or the Spec Compiler) starts a harness run that iterates
plan→execute→verify against spec-derived gates until an **external validator**
(E22 gates — never model self-approval) declares success or a typed stop state
(`max_iterations`/`max_budget`/`stalled`/`needs_human`/`error`) is reached;
the run is resumable after a crash, forkable, and every iteration's cost,
trace, and evidence are inspectable.

## Prior art (condensed)

Anthropic (agent loop with turn/budget controls; long-running dual-agent
pattern with feature-list + progress file; "Building Effective Agents"
patterns), Ralph loop (fresh context per iteration, state on disk, external
validator), Codex ("harness engineering", one harness across surfaces), Cursor
(parallel agents, race pattern), OpenHands/SWE-agent/LangGraph (controller
loop, ACI, durable checkpointing). Cross-cutting law: *the harness matters
more than the model*. Full comparison and sources in RFC-007.

## Stories

### E23-S1 — `harness.yaml` contract

Subtasks:
- `E23-S1-T1`: typed contract — `spec` ref (SemVer), `flow` ref, `loop` policy ref + parameters, `gates[]` (E22 verification gates that define "done"), `budgets` (per-iteration and total: tokens/cost/wallclock/iterations), `context` strategy (`compaction` | `fresh`), and typed result states (`success` / `max_iterations` / `max_budget` / `stalled` / `needs_human` / `error`).
- `E23-S1-T2`: published `harness.schema.json` + SDK export; harness registry persistence (tenant-scoped, SemVer, immutable published — same pattern as E20-S2).
- `E23-S1-T3`: `harness.*` events (`harness.run.started`, `.iteration.completed`, `.gate.evaluated`, `.run.finished` with result state) added append-only.

| Criterion | Detail |
| --- | --- |
| Functional | A valid `harness.yaml` resolves its spec/flow/gate refs at registration; a run always terminates in exactly one typed result state; `success` is only reachable through gate verdicts, never through model output alone |
| Non-functional | Contract additive to the SDK; refs frozen at run start for replayability (like flows) |
| DoR (specific) | RFC-007 accepted; epic ADR (harness boundary: what the harness owns vs. the Flow Engine) filed |
| DoD (specific) | Contract tests incl. every result state; `docs/harness/contract.md` |
| Dependencies | E20-S1, E3-S1 pattern, E22 (gate refs) |

### E23-S2 — Loop policies (pluggable)

Subtasks:
- `E23-S2-T1`: loop-policy extension point + four reference policies: **evaluator-optimizer** (a second agent scores and returns structured feedback), **fresh-context** (Ralph-style: each iteration starts a clean context re-hydrated from durable state), **circuit-breaker** (stagnation detection: no gate progress across N iterations → `stalled`), **heartbeat** (wake on schedule/event, act if needed).
- `E23-S2-T2`: loop execution on the Flow Engine — each iteration is a normal flow run (checkpointed, budgeted, traced); the harness layer only decides *whether and how* to start the next iteration. The Flow Engine is not modified.
- `E23-S2-T3`: context strategy enforcement — `compaction` uses the run's existing context path; `fresh` forbids carrying conversational context between iterations (state flows only through S3's durable artifacts).

| Criterion | Detail |
| --- | --- |
| Functional | A never-converging task stops as `stalled` via the circuit breaker (not `max_budget` exhaustion); a fresh-context run demonstrably shares no conversational tokens between iterations; evaluator feedback is structured and persisted per iteration |
| Non-functional | Fail-closed budgets at both iteration and run level (ADR-006 semantics); policy plugins pass a mandatory contract test |
| DoR (specific) | E23-S1 available; E4 strategy seam reviewed (policies compose with, not replace, reasoning strategies) |
| DoD (specific) | One test per reference policy incl. the stagnation fixture; `docs/harness/loops.md`; cross-link E37's harness/looping pattern catalog once available |
| Dependencies | E23-S1, E3, E4, E14 |

### E23-S3 — Durable loop state & session lifecycle

Subtasks:
- `E23-S3-T1`: durable harness state — a **gate/feature checklist** (every gate/acceptance item starts *failing*; only external verification flips it), an append-only **progress journal** (per-iteration summary for handoff), both persisted in the State Store and readable by the next iteration/session.
- `E23-S3-T2`: session-init sequence — on every iteration/resume: load checklist + journal tail + repo state (git log) before any new work; enforced by the harness, not left to the agent prompt.
- `E23-S3-T3`: resume/fork — resume an interrupted harness run from its last completed iteration (reusing E3-S3 checkpointing); fork a run (same spec/harness, divergent state) for exploration.

| Criterion | Detail |
| --- | --- |
| Functional | Killing the process mid-iteration and resuming loses at most the in-flight iteration; the checklist never flips to passing without a gate verdict recorded; a fork shares history up to the fork point and diverges after |
| Non-functional | State reconstruction from journal+checklist alone is sufficient for a fresh-context iteration (no hidden memory) |
| DoR (specific) | E23-S1/S2 available; E3-S3 checkpoint semantics reviewed |
| DoD (specific) | Crash/resume and fork tests; `docs/harness/state.md`; no raw prior-agent transcript is required for reconstruction |
| Dependencies | E23-S1, E23-S2, E3-S3, E8 |

### E23-S4 — Parallel isolation, task claiming & candidate race

Subtasks:
- `E23-S4-T1`: per-task isolation — each parallel harness task executes against its own git worktree (or sandbox container copy), patches merged back through the existing patch workflow.
- `E23-S4-T2`: task claiming — a lock record (State Store row or Redis lock, reusing E0-S6) marks a task claimed so N parallel workers never duplicate work; stale claims expire.
- `E23-S4-T3`: candidate race — run the same task as N candidate runs (different agent/model/strategy via the E5 Selector), then an evaluator (E22 gates + E5 evals) picks the winner; losers' runs retained for comparison.

| Criterion | Detail |
| --- | --- |
| Functional | Two workers cannot claim the same task (contention test); parallel tasks on the same repo do not corrupt each other's working tree; a race produces one winning patch chosen by gate/eval score with the decision traced |
| Non-functional | Worktree/container setup overhead bounded and measured; aggregate budgets across candidates fail closed (a race cannot overspend the parent budget) |
| DoR (specific) | E23-S2 available; E14-S4 sandbox and patch runner reviewed; E0-S6 locks reviewed |
| DoD (specific) | Contention, isolation, and race tests; `docs/harness/parallel.md` |
| Dependencies | E23-S2, E23-S3, E14-S4, E0-S6, E5 |

### E23-S5 — Harness observability & `/v2/harnesses` API

Subtasks:
- `E23-S5-T1`: `/v2/harnesses` (register/list) + `/v2/harnesses/{id}/runs` (start/list) + run detail with per-iteration breakdown (gate states, cost, duration, evidence links), following §14.1 conventions.
- `E23-S5-T2`: per-iteration OTel traces and cost/token metrics (extending the E2/E3 metric families with iteration dimensions).
- `E23-S5-T3`: SSE streaming of `harness.*` events over the E9-S2 transport (cursor resume, type filters).

| Criterion | Detail |
| --- | --- |
| Functional | An operator can watch a harness run iterate live, see which gates flipped in each iteration, and retrieve any iteration's evidence bundle; the full harness lifecycle is drivable via `/v2` only (API-first, §2.13) |
| Non-functional | Streaming starts < 1 s (inherited from E9-S2); no unbounded event fan-out (per-iteration summary events, not raw token streams) |
| DoR (specific) | E23-S1 events defined; E9-S2 transport reviewed |
| DoD (specific) | API contract tests; streaming resume test; `docs/harness/api.md` |
| Dependencies | E23-S1, E9-S1, E9-S2 |

## v1/v2 precursor / starting point

- The Flow Engine (E3) already provides checkpointed, budgeted, human-in-the-
  loop DAG execution, and the reference flow encodes a plan→code→validate
  rework loop — but a loop today is ad-hoc flow config with no typed result
  states, no external-validator "done", no durable checklist/journal, no
  stagnation detection, and no cross-run identity. E23 names that missing
  layer; it deliberately owns *iteration policy and durable loop state* and
  nothing the Flow Engine already does.
- E4's reasoning strategies (Reflection, ToT) are *inner*-loop primitives; E23
  loop policies are the *outer* loop. The epic ADR must draw this boundary
  explicitly (same discipline as ADR-007/ADR-008).
- Worktree/lock mechanics have precedents: E0-S6 Redis locks and the sandbox
  runner exist; nothing does per-task worktrees or candidate races today.

## Epic exit checklist

- [ ] All 5 stories meet the global DoD plus story-specific DoD above.
- [ ] Contract tests green for `harness.yaml`, the loop-policy extension
      point, durable state, and the API surface.
- [ ] Epic ADR (harness vs. Flow Engine boundary; result-state vocabulary)
      filed before E23-S1 implementation starts.
- [ ] `harness.*` events documented append-only in the event catalog.
- [ ] `docs/v2_platform/progress.md` updated.
