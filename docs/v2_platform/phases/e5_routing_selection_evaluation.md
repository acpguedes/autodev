# E5 — Routing / Selection / Evaluation

**Wave:** Beta
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E2, E4
**Enables:** E7-S3 (retrieval eval), E12-S3
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.6 (E5), §18.8, §18.9

## Objective

Deliver the **Router & Selector** (task classification and choice of agent/model/
strategy by policy/cost) and the **Evaluation Service**, closing the feedback loop.

## Key result

A task is classified, routed, and assigned to the best agent/model/strategy; evals
measure quality and feed back into routing.

## Stories

### E5-S1 — Router (intent/task classification)

Subtasks:
- `E5-S1-T1`: pluggable classifier.
- `E5-S1-T2`: intent -> execution-path mapping.
- `E5-S1-T3`: decision trace.

| Criterion | Detail |
| --- | --- |
| Functional | A task is classified and routed to the correct path; the decision is traced with justification |
| Non-functional | Routing decision p95 < 150 ms; classifier is pluggable (extension point) |
| DoR (specific) | Initial intent taxonomy defined |
| DoD (specific) | Contract tests; routing-accuracy metrics |
| Dependencies | E2-S2, E4-S1 |

### E5-S2 — Selector (agent/model/strategy by policy and cost)

Subtasks:
- `E5-S2-T1`: capability-based matching.
- `E5-S2-T2`: cost/quality policy.
- `E5-S2-T3`: deterministic tie-breaking.

| Criterion | Detail |
| --- | --- |
| Functional | Selector chooses a candidate by capabilities + policy + cost; the choice is reproducible given the same state |
| Non-functional | Selection p95 < 100 ms; respects tenant budgets and quotas |
| DoR (specific) | Cost x quality objective function agreed |
| DoD (specific) | Deterministic-selection test; decision trace |
| Dependencies | E5-S1, E2-S2 |

### E5-S3 — Evaluation Service (offline/online evals)

Subtasks:
- `E5-S3-T1`: `eval.yaml` spec (dataset+rubric+metrics).
- `E5-S3-T2`: offline/online execution.
- `E5-S3-T3`: result storage.

| Criterion | Detail |
| --- | --- |
| Functional | An eval runs over a dataset and produces a score per rubric; the Evaluator is pluggable (rubric/LLM-as-judge/metric) |
| Non-functional | Results versioned and reproducible; parallel execution scales |
| DoR (specific) | Dataset/rubric format defined |
| DoD (specific) | Evaluator contract tests; `docs/evals/spec.md` |
| Dependencies | E2-S2, E0-S2 |

### E5-S4 — Eval -> routing feedback loop

Subtasks:
- `E5-S4-T1`: publish scores as a signal.
- `E5-S4-T2`: adjust Selector policy by result.
- `E5-S4-T3`: guard against regression.

| Criterion | Detail |
| --- | --- |
| Functional | Eval scores influence subsequent selection; detected regression blocks promotion |
| Non-functional | Policy change auditable; no unstable loop (hysteresis/guard) |
| DoR (specific) | Promotion/regression criterion defined |
| DoD (specific) | Closed-feedback test; policy-change event |
| Dependencies | E5-S2, E5-S3 |

## v1 precursor / starting point

- `SupervisorPolicy` (`backend/orchestrator/routing.py`) is defined but **not wired
  into the execution path** (`docs/feature_matrix.md` § Agent System) — it is the
  direct precursor to E5-S1/E5-S2 and should inform the initial classifier/selector
  design, but it currently has no cost policy, no capability matching against a real
  Agent Registry, and no evaluation feedback.
- There is no Evaluation Service and no evals today; E5-S3/E5-S4 start from zero.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Contract tests green for the Router, Selector, and Evaluator extension points.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Beta wave entry item "Router & Selector + Evaluation Service" satisfied (§18.9).
