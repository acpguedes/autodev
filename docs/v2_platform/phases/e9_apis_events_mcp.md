# E9 — APIs, Events & MCP

**Wave:** Split — E9-S1 (Control Plane API /v2 core, minimal) targets Alpha;
E9-S2/S3/S4 (streaming, event catalog, MCP) target Beta.
**Status:** In progress · E9-S1 (Control Plane API /v2 core) and E9-S3 (event catalog + canonical envelope) done · **Stories:** 2/4 complete
**Depends on:** E8, E2, E6 (RBAC is integrated later via E11-S2, not a hard dependency
of the API core — see §18.8 note)
**Enables:** E10; exposes streaming/events/MCP
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.3 (E9), §18.8, §18.9

## Objective

Expose the **Control Plane API /v2** (FastAPI) with sessions, flows, runs, config, and
registries; run streaming; an Event Bus **event catalog**; and **MCP**
interoperability.

## Key result

Clients (UI, CLI, external agents) operate the platform through versioned `/v2`
contracts (`schemaVersion`), receive run streaming in < 1 s, and integrate tools via
MCP.

## Stories

### E9-S1 — Control Plane API /v2 (core)

Subtasks:
- `E9-S1-T1`: versioned REST endpoints for sessions, flows, runs, config, and registries.
- `E9-S1-T2`: typed models with `schemaVersion` and input/output validation.
- `E9-S1-T3`: authentication and RBAC integration (delegated to E11).
- `E9-S1-T4`: published OpenAPI and API contract tests.

| Item | Content |
| --- | --- |
| CF | CRUD of key resources under `/v2`; standardized errors; consistent pagination/filtering; generated OpenAPI |
| CNF | Read p95 < 300 ms; backward compatibility within a MAJOR; RBAC mandatory in production |
| DoR | E8 (persistence) and approved resource contracts; §7 conventions followed |
| DoD | Contract tests green; OpenAPI published; `/v2` API docs |
| Dependencies | E8 (RBAC is not a prerequisite of the core; role-based authorization is integrated later via E11-S2 — see §18.9) |

### E9-S2 — Run streaming

Subtasks:
- `E9-S2-T1`: streaming transport (SSE/WebSocket) for run/step events.
- `E9-S2-T2`: backpressure and reconnection resuming by event cursor.
- `E9-S2-T3`: filtering by event type and tenant scope.

| Item | Content |
| --- | --- |
| CF | A client subscribes to a run and receives steps/decisions in real time; reconnects without losing events (cursor) |
| CNF | Streaming start < 1 s; supports >= 100 concurrent subscriptions per node; no cross-tenant leakage |
| DoR | E8-S2 (event store) ready; event catalog defined |
| DoD | Reconnect/resume test; streaming-latency metrics; docs |
| Dependencies | E8-S2, E9-S1 |

### E9-S3 — Event catalog and Event Bus

Subtasks:
- `E9-S3-T1`: central registry of event types (`domain.entity.action`) with schema.
- `E9-S3-T2`: async publish/subscribe between subsystems and plugins.
- `E9-S3-T3`: versioning and compatible event evolution.

| Item | Content |
| --- | --- |
| CF | Published events follow their registered schema; plugins subscribe by type; catalog documented and browsable |
| CNF | Resilient async delivery (retry/dead-letter); evolution without breakage within a MAJOR |
| DoR | §7 naming approved; Redis/broker provisioned |
| DoD | Schemas validated in CI; catalog published; publish/subscribe contract test |
| Dependencies | E8-S2 |

### E9-S4 — MCP interoperability

Subtasks:
- `E9-S4-T1`: expose platform tools/skills as an MCP server.
- `E9-S4-T2`: consume external MCP servers as agent tools.
- `E9-S4-T3`: map MCP permissions to the least-privilege model.

| Item | Content |
| --- | --- |
| CF | Agents use external MCP tools; internal tools exposed via MCP; discovery and explicit permissions |
| CNF | Isolation and least privilege; timeouts and budgets applied to MCP calls |
| DoR | E2 (Agent Runtime) and E6 (Skills) ready; MCP contract approved |
| DoD | Interop tested with a reference MCP server; docs; contract test |
| Dependencies | E2, E6, E9-S1 |

## v1 precursor / starting point

- FastAPI routers already exist with auto-discovery
  (`backend/api/routers/__init__.py`), but they are ad hoc endpoints, not versioned
  under `/v2` and without `schemaVersion` — the closest precursor to E9-S1, requiring
  a deliberate versioning pass rather than a rewrite from zero.
- There is no SSE/WebSocket streaming today (`GET /sessions/{id}/runs/{run_id}/stream`
  is `planned`, tracked as Unit 6 in `docs/implementation/mvp_refactor_plan.md`), no
  event catalog/Event Bus, and no MCP interoperability — E9-S2/S3/S4 start from zero.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Contract tests green for `/v2` API surface, streaming transport, event schemas,
      and the MCP adapter.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Alpha exit criterion "minimal Control Plane API /v2" (E9-S1) and Beta entry item
      "streaming, event catalog, MCP" (E9-S2/S3/S4) satisfied per §18.9.
