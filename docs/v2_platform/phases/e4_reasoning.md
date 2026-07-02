# E4 — Reasoning

**Wave:** Beta
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E1, E2
**Enables:** E5; consumed by E11-S3 (budgets)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.6 (E4), §18.8, §18.9

## Objective

Provide the **Reasoning Engine** with pluggable **Reasoning Strategies** (ReAct,
Plan-and-Execute, Reflection, Debate/ToT), governed by policies, budgets, and traces.

## Key result

An agent selects a pluggable reasoning strategy by policy; every reasoning step is
traced, budgeted, and reproducible.

## Stories

### E4-S1 — Reasoning Strategy contract (extension point)

Subtasks:
- `E4-S1-T1`: typed strategy interface.
- `E4-S1-T2`: instrumented step-by-step cycle.
- `E4-S1-T3`: strategy contract tests.

| Criterion | Detail |
| --- | --- |
| Functional | A strategy implements the contract and is pluggable; every step emits a trace; output conforms to the agent's IO |
| Non-functional | Contract tests mandatory; instrumentation overhead < 5% |
| DoR (specific) | Contract surface approved (RFC) |
| DoD (specific) | Schema in the SDK; `docs/reasoning/contract.md` |
| Dependencies | E1-S1, E2-S3 |

### E4-S2 — Reference strategies (ReAct, Plan-and-Execute)

Subtasks:
- `E4-S2-T1`: ReAct.
- `E4-S2-T2`: Plan-and-Execute.
- `E4-S2-T3`: comparative tests.

| Criterion | Detail |
| --- | --- |
| Functional | Both run via the Reasoning Engine and produce valid output; swappable without changing the agent |
| Non-functional | Honor budgets (fail closed); coverage >= 85% |
| DoR (specific) | Reference tasks for comparison defined |
| DoD (specific) | Comparable traces; SDK examples |
| Dependencies | E4-S1 |

### E4-S3 — Advanced strategies (Reflection, Debate/ToT)

Subtasks:
- `E4-S3-T1`: Reflection.
- `E4-S3-T2`: Debate/Tree-of-Thoughts.
- `E4-S3-T3`: fan-out cost control.

| Criterion | Detail |
| --- | --- |
| Functional | Reflection reviews and corrects; Debate/ToT explores and converges; fan-out limited by budget |
| Non-functional | Fan-out cost accounted per run; step ceiling enforced |
| DoR (specific) | Default fan-out limits defined |
| DoD (specific) | Convergence test and cost-ceiling test |
| Dependencies | E4-S1 |

### E4-S4 — Reasoning policies and budgets

Subtasks:
- `E4-S4-T1`: declarative strategy-selection policy.
- `E4-S4-T2`: per-strategy budgets.
- `E4-S4-T3`: fallback on overrun.

| Criterion | Detail |
| --- | --- |
| Functional | A policy selects the strategy by context; overrun triggers the defined fallback |
| Non-functional | Fails closed by default; policy decision traced |
| DoR (specific) | Policy DSL/format agreed |
| DoD (specific) | Selection and fallback tests; `docs/reasoning/policies.md` |
| Dependencies | E4-S1, E2-S3 |

## v1 precursor / starting point

- There is no reasoning-strategy abstraction today. Agents in
  `backend/agents/base.py` are pure prompt-to-text (single LLM call, no
  ReAct/Plan-and-Execute loop, no tool-use), so E4 starts from zero. The planned
  agent tool-use loop (Unit 25 of `docs/implementation/mvp_refactor_plan.md`) is a
  useful precursor for the ReAct-style step cycle in E4-S1/E4-S2, since a bounded
  observe/act loop with tool bindings is a prerequisite for any real ReAct
  implementation.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Contract tests green for the Reasoning Strategy extension point.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Beta wave entry item "Reasoning" satisfied (§18.9).
