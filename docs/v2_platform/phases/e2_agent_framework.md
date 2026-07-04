# E2 — Agent Framework

**Wave:** Alpha
**Status:** In progress · **Stories:** 2/5 complete
**Depends on:** E0, E1
**Enables:** E4, E5, E9-S4
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.6 (E2), §18.8, §18.9

## Objective

Define the **Agent Manifest**, typed IO contracts, and the **Agent Registry**, making
agents first-class **plugins** with declared **capabilities**.

## Key result

An `agent.yaml` publishes an agent with capabilities and an IO schema; the Agent
Runtime instantiates it, applies budgets/guardrails, and executes it to produce output
per contract.

## Stories

### E2-S1 — `agent.yaml` specification and IO schema — Done

Subtasks:
- `E2-S1-T1`: schema (id, version, capabilities, IO, tools/skills, policy, budgets).
- `E2-S1-T2`: typed IO validation.
- `E2-S1-T3`: capability versioning.

| Criterion | Detail |
| --- | --- |
| Functional | Agent declares capabilities and IO schema; input/output outside the schema is rejected; budgets inherit a safe default |
| Non-functional | IO validation < 20 ms; contract tests per capability |
| DoR (specific) | Initial capability vocabulary agreed |
| DoD (specific) | Schema in the SDK; `docs/agents/manifest.md` |
| Dependencies | E1-S1 |

### E2-S2 — Agent Registry (registration/discovery/versioning) — Done

Subtasks:
- `E2-S2-T1`: registry persistence.
- `E2-S2-T2`: search by capability.
- `E2-S2-T3`: SemVer version resolution.

| Criterion | Detail |
| --- | --- |
| Functional | Searching agents by capability returns rankable candidates; multiple versions coexist; deprecation is signaled |
| Non-functional | Search p95 < 100 ms; registry consistent with the Plugin Host |
| DoR (specific) | Registry query contract defined |
| DoD (specific) | `/v2` catalog endpoint; version-resolution test |
| Dependencies | E2-S1, E1-S5 |

### E2-S3 — Agent Runtime (execution, budgets, guardrails)

Subtasks:
- `E2-S3-T1`: agent execution cycle.
- `E2-S3-T2`: budget enforcement (tokens/cost/time/steps).
- `E2-S3-T3`: output guardrails.

| Criterion | Detail |
| --- | --- |
| Functional | Agent exceeding budget -> interrupted and flagged; guardrail blocks/corrects out-of-policy output; failure records a step |
| Non-functional | Budgets **fail closed**; runtime overhead < 8%; trace per step |
| DoR (specific) | Default per-run budgets defined (reference doc §6) |
| DoD (specific) | Budget-overrun and guardrail tests; token/cost metrics emitted |
| Dependencies | E2-S1, E0-S3 |

### E2-S4 — Tool/skill mediation and LLM provider

Subtasks:
- `E2-S4-T1`: permissioned tool broker.
- `E2-S4-T2`: provider abstraction (local stub <-> real).
- `E2-S4-T3`: per-call token/cost metering.

| Criterion | Detail |
| --- | --- |
| Functional | Agent only accesses granted tools/skills; stub provider runs offline; switching provider does not change the agent |
| Non-functional | Least privilege on tools; cost accounted per run/tenant; no network in the sandbox by default |
| DoR (specific) | Provider interface defined |
| DoD (specific) | Test with stub and with a mocked real provider; `docs/agents/runtime.md` |
| Dependencies | E2-S3, E1-S3 |

### E2-S5 — Reference agent `autodev/agent-coder` as a plugin

Subtasks:
- `E2-S5-T1`: package the existing v1 agent as a plugin.
- `E2-S5-T2`: declare capabilities/IO.
- `E2-S5-T3`: migrate behavior with parity.

| Criterion | Detail |
| --- | --- |
| Functional | `autodev/agent-coder` runs via the Agent Runtime with functional parity to v1; installable/uninstallable |
| Non-functional | No quality regression vs. the v1 baseline; coverage >= 85% |
| DoR (specific) | v1 behavior baseline captured |
| DoD (specific) | Parity suite green; SDK example |
| Dependencies | E2-S3, E2-S4, E1-S4 |

## v1 precursor / starting point

- `backend/agents/registry.py` (auto-discovery) and `backend/agents/contracts.py`
  (typed metadata contracts exposed via `GET /agents/contracts`) already exist and are
  `default` — the closest analogue to E2-S1/E2-S2, but contracts are hardcoded per
  agent rather than self-declared via an `agent.yaml` manifest with capabilities.
- Specialized agents (`security`, `refactor`, `docs`) already exist under
  `backend/agents/{security,refactor,docs}/` and are discoverable, but are not part of
  the default pipeline order — a natural first candidate set for E2-S5-style
  packaging once `agent-coder` establishes the pattern.
- Agents today are pure prompt-to-text with **no tool-use loop**
  (`backend/agents/base.py`) — an agentic read/edit/run/observe loop is tracked
  separately as Unit 25 in `docs/implementation/mvp_refactor_plan.md` and is a direct
  precursor to E2-S4's tool broker.

## Epic exit checklist

- [ ] All 5 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Contract tests green for the agent IO/capability extension points.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Alpha wave exit criteria this epic contributes to (§18.9) satisfied.
