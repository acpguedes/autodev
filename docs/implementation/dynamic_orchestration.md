# Specialized agents, registry & dynamic orchestration

## Specialized agents (`backend/agents/{security,refactor,docs}/`)

Three additional agents extend the fixed core roster, each self-registering via
`@register_agent(...)` and carrying a typed metadata contract in
`backend/agents/contracts_ext.py`:

- `security` — `SecurityOutput{findings, severity, recommendations}`
- `refactor` — `RefactorOutput{targets, smells, suggested_changes}`
- `docs` — `DocsOutput{documents, sections, summary}`

They are **discoverable** (resolvable via the registry / `OrchestratorService`) but are not
added to the linear `agent_order`, so the default `/chat` pipeline is unchanged.

## Agent registry surface (`backend/api/routers/agents_registry.py`, `backend/cli_plugins/agents.py`)

- `GET /agents` — every agent (8 core + registered custom) with a has-contract flag.
- `GET /agents/{name}` — details, including the JSON schema when the agent declares a
  `metadata_model`.
- `autodev agents list` — the same inventory from the CLI.

This is distinct from the pre-existing `GET /agents/contracts` (which publishes only the
typed metadata schemas of the core agents).

## Dynamic routing (`backend/orchestrator/routing.py`, `backend/orchestrator/graphs.py`)

- `RunTypeRouter` maps each `RunType` to an ordered subset of agents (e.g.
  `VALIDATION_ONLY -> [navigator, validator, responder]`).
- `SupervisorPolicy.next_agent(state)` chooses the next agent or stops.
- `build_conditional_graph(agents, order)` / `build_graph_for_run_type(...)` compile a
  LangGraph from an explicit order.

This module is standalone and is **not** wired into the default run path.

## Opt-in endpoint (`backend/api/routers/orchestration.py`)

- `POST /chat/dynamic` — when `AUTODEV_DYNAMIC_ORCH=1`, runs the run-type-routed graph;
  otherwise (or on import error) it falls back to `OrchestratorService.handle_message`. The
  original `/chat` is untouched.

```bash
AUTODEV_DYNAMIC_ORCH=1 uvicorn backend.api.main:app
curl -X POST localhost:8000/chat/dynamic \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "<id>", "message": "validate the repo"}'
```
