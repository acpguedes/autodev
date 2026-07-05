# Agent Runtime

The v2 Agent Runtime is the mandatory execution boundary for agents. Agent handlers
receive an `AgentRuntimeContext`; they do not call tools, skills, or LLM providers
directly.

## Execution Cycle

1. Validate input against the `agent.yaml` IO input schema.
2. Invoke the agent handler with a mediated context.
3. Enforce budgets on every recorded step, tool/skill call, and LLM call.
4. Validate output against the IO output schema.
5. Apply output guardrails.
6. Return structured status, steps, metrics, and output.

Budget exhaustion interrupts execution with `stop_reason: budget_exhausted`.
Guardrail blocks return `stop_reason: guardrail_blocked`. Both paths fail closed and
record a failed step.

## Tools And Skills

`AgentToolBroker` exposes only ids declared in `agent.yaml`:

```python
ctx.call_tool("fs.read", path="README.md")
ctx.call_skill("autodev/skill-unified-diff", before="", after="")
```

Undeclared tools or skills raise `ToolAccessDenied`. Network access is denied when
`permissions.network` is omitted or set to `none`, which is the default.

## Providers

Agents call `ctx.call_llm(prompt)`. The runtime owns the provider object, so switching
from the offline `StubLLMProvider` to a real provider does not change agent code.
Provider responses carry token and cost usage:

```python
LLMProviderResponse(text="...", tokens_input=10, tokens_output=4, cost_usd=0.02)
```

The runtime records `tokens.input`, `tokens.output`, `cost.usd`, `tool.calls`, and
`steps` per run and tenant.
