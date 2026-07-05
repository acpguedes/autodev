# Reasoning Policies, Budgets, and Selection (E4-S4)

A **reasoning policy** (`reasoning-policy.yaml`) is a declarative, versioned
document that governs, for a reasoning run: which strategy runs, the budget
ceiling, what happens on overrun, guardrails, and tracing. The authoritative
spec is `docs/architecture/v2_platform_reference.md` §8.4/§8.7; this page is the
practical guide. Schema:
`backend/reasoning/schemas/reasoning-policy.schema.json`.

```yaml
schemaVersion: 1
id: autodev/reasoning-policy-default
version: 1.2.0
hostApi: ">=2.0 <3.0"

selection:
  default: autodev/reasoning-react
  rules:
    - when: { task.kind: "code_patch" }
      use: autodev/reasoning-reflection
      config: { max_revisions: 2 }
    - when: { complexity: ">=high" }
      use: autodev/reasoning-plan-execute

budget:
  tokens: 24000
  cost_usd: 0.75
  wall_clock_ms: 45000
  max_steps: 12
  on_exceed: fail_closed        # or degrade_to:<strategy-id>

guardrails:
  - { id: no_secret_leakage, on_violation: block }

tracing: { level: full, record_prompts: true, deterministic_replay: true }
```

## Strategy selection

`resolve_strategy(policy, *, context, manifest_strategy, node_override,
selector_choice)` (`backend/reasoning/selection.py`) chooses the strategy by the
**precedence of reference §8.7** — increasing priority:

1. `default` — the policy's fallback strategy.
2. `policy_rule` — the first matching `selection.rules` entry.
3. `manifest` — a strategy declared on the Agent Manifest.
4. `flow_node` — a Flow Node override.
5. `selector` — a dynamic Selector choice (E5).

The higher tier wins; the returned `SelectionDecision` records the `source`, so
the choice is auditable. Rule predicates are **operator-aware**: values may be
plain (`"code_patch"`), numeric comparisons (`">=20000"`), or ordinal-level
comparisons (`">=high"`, where `low < medium < high < critical`).

## Budgets and fallback

Budgets are enforced by the Engine and fail closed (see
`docs/reasoning/contract.md`). Precedence: **run > agent > policy** — the
smallest applicable ceiling wins; the Agent Runtime applies this via
`budget_from_agent_budgets` (`backend/reasoning/agent_binding.py`).

`on_exceed` controls overrun behavior:

- `fail_closed` (default) — the run ends `budget_exhausted`; nothing else runs.
- `degrade_to:<strategy-id>` — the `ReasoningService` retries once with the named
  fallback strategy, emitting a `reasoning.selection.degraded` trace event.

## Running via the service

`ReasoningService` (`backend/reasoning/service.py`) ties the registry, the
selector, and the Engine together and applies the fallback:

```python
from backend.reasoning import ReasoningService, ReasoningStrategyRegistry, reasoning_input_from_agent
from backend.reasoning.strategies import register_builtin_strategies

registry = ReasoningStrategyRegistry()
register_builtin_strategies(registry)
service = ReasoningService(registry, on_event=trace_sink.append)

run_input = reasoning_input_from_agent(task=task, policy=policy, budgets=agent_budgets, tools=tools)
result = await service.run(run_input, context={"task.kind": "code_patch"})
# result.output.stop_reason, result.decision.source, result.degraded_to
```

## Agent Runtime binding

`backend/reasoning/agent_binding.py` is the seam between the Agent Runtime (E2)
and the Reasoning Engine: it maps an agent's `AgentBudgets` onto a reasoning
`Budget` and builds a `ReasoningInput`. Swapping the default single-call agent
step for a full reasoning run is progressive adoption (E5 Selector / E14
execution); the contract, engine, strategies, and this policy layer are the
foundation it builds on.
