# Reasoning Strategy Contract (E4-S1)

The **Reasoning Engine** is the component of the Agent Runtime that decides *how*
an agent thinks. It runs pluggable **Reasoning Strategies** (ReAct,
Plan-and-Execute, Reflection, Debate/ToT, native tool-calling) behind one typed,
versioned contract, enforcing budgets and guardrails and emitting an ordered
trace for replay. New strategies plug in at the `reasoning.strategy` extension
point without any change to the core.

This page is the practical guide. The authoritative specification is
`docs/architecture/v2_platform_reference.md` §8; the decisions are RFC-003 and
ADR-007.

## The contract

A strategy implements `backend.reasoning.contract.ReasoningStrategy`:

```python
from backend.reasoning import ReasoningContext, ReasoningInput, ReasoningOutput, Usage

class MyStrategy:
    id = "acme/reasoning-my-strategy"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def config_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        result = await ctx.call_llm([{"role": "user", "content": input.task}])
        verdict = await ctx.verify(result.content)          # guardrails
        return ReasoningOutput(
            content=result.content,
            stop_reason="completed",
            usage=Usage(),      # the Engine overrides usage/trace_id authoritatively
            trace_id="",
        )
```

Four rules the contract enforces (see RFC-003):

1. **All effects go through `ctx`** — never call a provider or tool directly.
2. **Stateless between runs** — state lives in the run trace/state, not on `self`.
3. **`await ctx.check_budget()` before each costly step** — the Engine also checks
   before every mediated call as a fail-closed backstop.
4. **`await ctx.verify(output)` on the final output** — run guardrails before
   returning.

The contract is `async` even though the surrounding runtime is synchronous
(ADR-007): the Engine `await`s the strategy while the LLM provider stays sync.

## Running a strategy

```python
import asyncio
from backend.reasoning import (
    ReasoningEngine, ReasoningInput, budget_from_policy, default_reasoning_policy,
)

policy = default_reasoning_policy(default_strategy="acme/reasoning-my-strategy")
engine = ReasoningEngine()          # offline StubLLMProvider by default
run_input = ReasoningInput(
    task="summarize the diff",
    messages=(),
    tools=(),
    policy=policy,
    budget=budget_from_policy(policy),
)
output = asyncio.run(engine.run(MyStrategy(), run_input))
# output.stop_reason ∈ {completed, budget_exhausted, guardrail_blocked, error}
```

### Budgets (fail-closed)

The Engine — not the strategy — enforces the `Budget` (`tokens`, `cost_usd`,
`wall_clock_ms`, `max_steps`). Every `call_llm`/`call_tool` first calls
`check_budget()`; once any ceiling is reached it raises `BudgetExceededError`,
**no further effect occurs**, and the run ends with
`stop_reason="budget_exhausted"`. Precedence (applied at the Agent Runtime
boundary, E4-S4): run > agent > policy — the smallest applicable ceiling wins.

### Guardrails

A policy lists guardrails with an action: `block` (fail closed →
`guardrail_blocked`), `repair_once` (one in-run repair window; unrepaired at the
Engine boundary ⇒ `guardrail_blocked`), or `warn` (record and proceed). Register
the actual check functions on the Engine:

```python
engine = ReasoningEngine(
    guardrail_checks={"no_secret_leakage": lambda out: "SECRET" not in str(out)},
)
```

### Traces

Every mediated step emits an ordered `TraceEvent` (`reasoning.run.started`,
`reasoning.llm.called`, `reasoning.guardrail.evaluated`, `reasoning.run.completed`,
…). Pass `on_event=...` to the Engine to receive the stream — this is the Event
Bus hook (E9) and what makes runs replayable (reference §8.6).

## Packaging as a plugin

A strategy ships as a plugin with a `reasoning-strategy.yaml` manifest
(schema: `backend/reasoning/schemas/reasoning-strategy.schema.json`):

```yaml
schemaVersion: "1"
kind: ReasoningStrategy
id: acme/reasoning-my-strategy
version: 1.0.0
hostApi: ">=2.0 <3.0"
entrypoint: { runtime: python, ref: acme_pkg.strategy:MyStrategy }
```

The `ReasoningStrategyRegistry` resolves strategies by SemVer and rejects any
whose `host_api` is incompatible with the platform (`2.0`).

## Policy document

`reasoning-policy.yaml` (schema:
`backend/reasoning/schemas/reasoning-policy.schema.json`) governs selection,
budgets, guardrails, and tracing (reference §8.4). E4-S1 ships the parser and a
minimal `select_strategy` (exact-match rules, default fallback); operator-aware,
Router/Selector-integrated selection is E4-S4.

## Built-in reference strategies (E4-S2)

Three first-party strategies ship in `backend/reasoning/strategies/` and run on
any provider, including the offline stub:

| Strategy | id | Loop |
| --- | --- | --- |
| ReAct | `autodev/reasoning-react` | Thought → `ACTION <tool> <args>` / `FINAL <answer>`, budget-bounded |
| Plan-and-Execute | `autodev/reasoning-plan-execute` | Plan (one step per line) → execute each step |
| Native tool-calling | `autodev/reasoning-native-tools` | Single mediated call; the provider drives tools |

```python
from backend.reasoning import ReasoningStrategyRegistry
from backend.reasoning.strategies import register_builtin_strategies

registry = ReasoningStrategyRegistry()
register_builtin_strategies(registry)
strategy = registry.resolve("autodev/reasoning-react")
```

Reflection and Debate/Tree-of-Thought (`autodev/reasoning-reflection`,
`autodev/reasoning-tot`) land in E4-S3.
