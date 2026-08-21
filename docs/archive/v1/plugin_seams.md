# Plugin seams (auto-discovery architecture)

> **Archived 2026-08-20 — v1 architecture.** This document describes the v1
> linear-pipeline design, frozen at the
> [`v1` release](https://github.com/acpguedes/autodev/releases/tag/v1).
> Superseded by E1's Plugin Host and `plugin.yaml` manifests — see [`docs/plugins/manifest.md`](../../plugins/manifest.md), [`docs/plugins/permissions.md`](../../plugins/permissions.md) and [`docs/plugins/registry.md`](../../plugins/registry.md).
> Retained as the design audit trail; **not maintained**. See
> [`docs/archive/v1/README.md`](README.md) for the full v1 -> v2 map.

The platform's multi-agent, skills, plans, patches, and validation capabilities are
added as **self-contained modules** that attach to the running app through three
additive "seams" installed once in the three otherwise-hot files
(`backend/api/main.py`, `backend/orchestrator/service.py`, `backend/cli.py`). After the
seams exist, a new capability is a **new file in a watched directory** — no edits to the
hot files are required, which keeps changes independent and conflict-free.

## The three seams

1. **API router auto-include** — `backend/api/routers/__init__.py::include_all_routers(app)`
   imports every module under `backend/api/routers/` and, for each, calls
   `app.include_router(module.router)` and `module.attach(app)` when present. A failing
   module is logged and skipped so it can never crash startup.
   - **Add an endpoint:** drop `backend/api/routers/<name>.py` exporting `router = APIRouter()`.

2. **Agent registry** — `backend/agents/registry.py` provides `register_agent(name)` and
   `discover_agents(project_root=None)`. `OrchestratorService._build_default_agents` merges
   discovered agents over the fixed core agents with `setdefault`, so custom agents are
   resolvable without changing the linear `agent_order` (existing runs are unaffected).
   - **Add an agent:** create `backend/agents/<name>/agent.py` and decorate the class with
     `@register_agent("<name>")`.

3. **CLI plugin loader** — `backend/cli_plugins/__init__.py::register_subcommands(subparsers)`
   imports every module under `backend/cli_plugins/` and calls its `register(subparsers)`.
   - **Add a subcommand:** create `backend/cli_plugins/<name>.py` exposing `register(subparsers)`.

All consumer modules import their backing subsystem lazily inside handlers and degrade
gracefully (HTTP 503 / clean CLI error) when the subsystem is absent, so every unit is
independently mergeable.

## Reserved namespaces

To avoid runtime collisions, each subsystem owns a unique HTTP path prefix and CLI verb.

| Subsystem            | HTTP                                                              | CLI verb            |
|----------------------|------------------------------------------------------------------|---------------------|
| Skills               | `GET /skills`, `GET /skills/{name}`, `POST /skills/{name}/invoke` | `autodev skills`    |
| Agents registry      | `GET /agents`, `GET /agents/{name}`                              | `autodev agents`    |
| Dynamic orchestration| `POST /chat/dynamic`                                              | —                   |
| Plans                | `GET/PUT /plans/{session_id}`, `POST /plans/{session_id}/approve\|reject` | `autodev plans` |
| Patches              | `POST /patches/generate`, `POST /patches/apply`                  | `autodev patches`   |
| Validation           | `POST /validation/run`, `GET /validation/{job_id}`               | `autodev validate`  |
| Repository symbols   | `GET /repository/symbols`                                        | —                   |
| Observability        | `GET /metrics`                                                   | —                   |
| Jobs                 | `POST /jobs`, `GET /jobs/{job_id}`                               | —                   |

> Pre-existing endpoints (unchanged): `/health`, `/config`, `/agents/contracts`, `/plan`,
> `/sessions...`, `/chat`, `/repository/context`. Note `/agents` (registry) is distinct from
> `/agents/contracts` (typed metadata schemas), and `/plans/*` is distinct from `/plan` and
> `/sessions/{id}/execution-plan`.
