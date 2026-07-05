# `autodev/agent-coder` v1 Baseline

E2-S5 packages the v1 `backend.agents.coder.agent.CoderAgent` as the reference v2
agent plugin. The parity baseline is the deterministic v1 fallback path, because it
runs offline and is already used when no configured LLM is available.

Baseline context:

```python
AgentContext(
    session_id="baseline",
    goal="Expose agent contracts",
    user_request="Expose agent contracts",
    artifacts={"planner": {"steps": ["Expose schemas", "Add tests"]}},
)
```

Expected metadata:

```json
{
  "coding_tasks": [
    {
      "component": "backend/api",
      "task": "Expose agent contract schemas through a typed API endpoint"
    },
    {
      "component": "backend/agents",
      "task": "Validate agent metadata against Pydantic contracts"
    },
    {
      "component": "tests/backend",
      "task": "Cover schema publishing and metadata validation behavior"
    },
    {
      "component": "docs",
      "task": "Document the structured-output slice and roadmap progress"
    }
  ],
  "test_updates": [
    "Add orchestrator coverage for contract exposure",
    "Assert API returns the expected schema documents"
  ],
  "touched_components": [
    "backend/api",
    "backend/agents",
    "tests/backend",
    "docs"
  ]
}
```

The v2 plugin output maps these fields to the `coder-io` contract as
`codingTasks`, `testUpdates`, and `touchedComponents`.
