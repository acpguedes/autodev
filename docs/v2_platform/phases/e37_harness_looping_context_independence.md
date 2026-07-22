# E37 — Harness & Looping Excellence: Context-Independent Agents

**Wave:** v2.3 — Platform Excellence (after E23-S1/S2; parts that only refine
contracts may be pulled into E23 before implementation).
**Status:** Not started · **Stories:** 0/5 complete
**Depends on:** E23 (Harness Engine & Loop Engineering), E26 (runtime context
engineering), E27 (candidate/verifier contracts), E8 (durable state), E14/E32
(real isolated execution)
**Enables:** reliable long-horizon work, safe parallelism, phase-level context
quarantine, better replay/debuggability, and SOTA harness/looping practices
without vendor lock-in.

## Objective

Make **harness engineering** and **looping engineering** first-class platform
disciplines rather than implementation style. Harnesses own the outer control
loop, stop conditions, evidence, state rehydration and candidate coordination;
looping policies own iteration decisions, stagnation detection, recovery and
cost-aware continuation. Agents in different phases communicate through typed
handoff artifacts, never by inheriting raw conversational context.

## Key result

A multi-phase run can be resumed, forked, debugged and audited from durable
state alone. Planner, implementer, verifier, critic/oracle and reviewer phases
share only explicit `PhaseHandoff` bundles; a failed or stalled loop has a typed
reason, bounded cost and evidence explaining the next safe action.

## Stories

### E37-S1 — `PhaseHandoff` schema and context quarantine

Subtasks:
- `E37-S1-T1`: define `PhaseHandoff` with `run_id`, `phase_id`, `agent_id`,
  `spec_id`, `task_id`, allowed inputs, artifact references, assumptions,
  unresolved questions, budget and schema version.
- `E37-S1-T2`: forbid raw transcripts, unclassified tool outputs, secrets and
  previous-agent hidden scratchpads by default; allow only explicitly typed
  summaries and evidence references.
- `E37-S1-T3`: require reconstruction tests: a fresh phase must reproduce its
  starting state from `PhaseHandoff` + State Store + artifact store only.

| Criterion | Detail |
| --- | --- |
| Functional | Planner→executor, executor→critic and candidate→oracle handoffs carry no prior conversational tokens unless explicitly whitelisted |
| Non-functional | Serialization deterministic; redaction and tenant scoping enforced before persistence |
| DoR (specific) | E23-S2/S3 and E26-S4 boundaries reviewed |
| DoD (specific) | `docs/harness/context_isolation.md`; leakage negative tests documented |
| Dependencies | E23, E26, E8 |

### E37-S2 — Harness engineering runbook and pattern catalog

Subtasks:
- `E37-S2-T1`: define reusable harness patterns: single-pass gate, evaluator-
  optimizer, fresh-context rehydration, plan/act/review, best-of-N race,
  heartbeat maintenance, repair loop and incident rollback loop.
- `E37-S2-T2`: for each pattern document inputs, loop policy, state, gates,
  stop states, budget semantics, evidence and safe degradation.
- `E37-S2-T3`: require every product mode that performs autonomous work to
  choose one named harness pattern rather than embedding ad-hoc loops.

| Criterion | Detail |
| --- | --- |
| Functional | A new autonomous workflow cannot be accepted without naming its harness pattern and loop policy |
| Non-functional | Patterns are provider-agnostic and local-first by default |
| DoR (specific) | E23 `harness.yaml` contract drafted |
| DoD (specific) | `docs/harness/patterns.md` linked from E14, E23, E24 and E27 |
| Dependencies | E23-S1, E23-S2 |

### E37-S3 — Looping engineering stop/recovery taxonomy

Subtasks:
- `E37-S3-T1`: extend result states with typed recovery hints:
  `retryable_environment`, `retryable_dependency`, `needs_spec_delta`,
  `needs_human_decision`, `weak_oracle`, `stalled_no_progress`,
  `budget_exhausted`, `unsafe_action`.
- `E37-S3-T2`: require loop policies to emit a machine-readable continuation
  recommendation: `continue`, `retry_same`, `retry_with_new_context`,
  `fork_candidate`, `ask_human`, `stop`, `rollback`.
- `E37-S3-T3`: add loop-debug evidence: last progress delta, gate deltas,
  cost delta, context-diff hash and artifact links.

| Criterion | Detail |
| --- | --- |
| Functional | A stalled run explains why another iteration is or is not justified |
| Non-functional | Stop/recovery states are stable enums suitable for API clients |
| DoR (specific) | E23 typed result states available |
| DoD (specific) | Loop taxonomy documented and covered by contract tests |
| Dependencies | E23-S1, E23-S2, E12 |

### E37-S4 — Parallel agent independence and merge arbitration

Subtasks:
- `E37-S4-T1`: define per-agent workspaces/worktrees, task claims, artifact
  namespaces and merge intents for independent phases and candidates.
- `E37-S4-T2`: add merge arbitration contract: accepted patch, rejected patch,
  split patch, conflict requiring human, or spec/task decomposition correction.
- `E37-S4-T3`: require losing candidates and rejected patches to remain
  inspectable for learning/evaluation without leaking their context into the
  winning agent's phase.

| Criterion | Detail |
| --- | --- |
| Functional | Parallel candidates cannot mutate the same working tree and cannot read one another's private context by default |
| Non-functional | Arbitration decisions are auditable and costed |
| DoR (specific) | E23-S4 and E27-S1 reviewed |
| DoD (specific) | Contention, merge-conflict and context-leak fixtures documented |
| Dependencies | E23-S4, E27-S1, E32 |

### E37-S5 — Harness/loop telemetry and replay debugger

Subtasks:
- `E37-S5-T1`: define per-loop metrics: iteration count, progress delta,
  gate flips, context size, cache-hit rate, budget burn rate, verifier
  disagreement, human intervention count and rollback count.
- `E37-S5-T2`: define replay debugger views: iteration timeline, handoff
  bundle, gate/evidence diff, cost breakdown and stop/recovery reason.
- `E37-S5-T3`: feed loop telemetry into the capability benchmark and FinOps
  reports so loop quality is measured, not inferred.

| Criterion | Detail |
| --- | --- |
| Functional | A reviewer can replay why each iteration happened and why the loop stopped |
| Non-functional | Telemetry avoids raw token/event fan-out; summaries are bounded and redacted |
| DoR (specific) | E23-S5 API and E26 metrics reviewed |
| DoD (specific) | Metrics catalog and replay-debug UX contract documented |
| Dependencies | E23-S5, E26-S1, E30 |

## Epic exit checklist

- [ ] All 5 stories meet the global DoD plus story-specific DoD above.
- [ ] `PhaseHandoff`, loop taxonomy and harness pattern docs are linked from E23/E26/E27.
- [ ] `docs/v2_platform/progress.md` updated.
