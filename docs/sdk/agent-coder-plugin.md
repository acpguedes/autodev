# Reference Agent Plugin Example

`examples/plugins/agent-coder` is the SDK example for packaging an agent as a plugin.
It contains:

- `plugin.yaml` declaring an E1 `agent` extension point.
- `agent.yaml` declaring the v2 agent contract, capabilities, IO, permissions, and
  budgets.
- `contracts/*.schema.json` for strict input and output validation.
- `autodev_agent_coder.py`, an in-process handler loaded by the Agent Runtime.

Run its contract and parity tests from the repository root:

```bash
python -m pytest backend/tests/test_agent_coder_plugin.py -q
```

The handler adapts the v1 `CoderAgent.fallback_result` output into the v2
`autodev/coder-io` schema, so the example runs fully offline with the stub runtime.
