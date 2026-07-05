# Flow Engine — Execution, Durable State, Triggers, and Events

> Delivered by **E3-S2** (graph execution with durable Run/Step state) and
> **E3-S4** (human-in-the-loop).
> Manifest contract: `docs/flows/spec.md`. Implementation:
> `backend/flows/engine.py` (executor), `backend/flows/state.py` +
> `backend/flows/records.py` (durable Run/Step/Event store),
> `backend/flows/registry.py` (versioned definitions),
> `backend/flows/handlers.py` (node handlers),
> `backend/flows/human.py` + `backend/flows/pause.py` (human-in-the-loop),
> `backend/flows/triggers.py` (triggers), `backend/api/routers/flows.py`
> (`/v2/flows` API).

## Execution model

`FlowEngine.start_run()` resolves the flow (SemVer range) from the registry,
validates the run input against the declared input schema (required fields;
undeclared fields when `additionalProperties: false`), persists a run, emits
`flow.run.started`, and executes the graph:

1. The cursor starts at the entry node and is **persisted in the run state**
   after every step, together with each node's output
   (`state.nodes.<id>.output`) and accumulated metrics.
2. Each activation persists a Step (`running` → `completed`/`failed`, with
   attempt counter and sequence), wrapped in an OpenTelemetry span
   (`autodev.run.step.*`, non-PII attributes).
3. Routing evaluates the node's outgoing edges in declaration order: the first
   `when` predicate that matches wins, otherwise the single unguarded edge.
   `on`-signal edges are never taken by normal completion. If edges exist and
   none match, the run **fails closed** (`no_route`).
4. The run completes when the cursor reaches a terminal node; the consolidated
   output is the last completed node's output.

Failures never propagate as exceptions to callers: a failing node fails its
step, emits `run.step.failed`, and terminates the run as `failed` with a
machine-readable `stop_reason` (`node_failed`, `unsupported_node`,
`binding_error`, `predicate_error`, `no_route`, `budget_exhausted`).

## Durable state

Three tables (SQLite locally, PostgreSQL in production — same store selection
as ADR-001): `flow_runs` (status, trigger, input, state, output, tenant,
parent run), `flow_steps` (per-activation status/attempt/IO/sequence), and
`flow_events` — the **ordered event store** consumed by replay (E3-S3).
State survives process restarts; a second engine instance on the same store
sees identical runs, steps, and events. On SQLite the store uses WAL,
per-connection busy timeouts, and eager write transactions so ≥100 concurrent
runs per node execute without lock failures (covered by a concurrency test).

## Budgets (fail closed)

Manifest budgets are enforced between activations: wall clock, accumulated
tokens, and accumulated cost (agent nodes report the E2 runtime's metrics).
An engine-level step cap (default 1000 activations per run) additionally
bounds guarded loops that never exit. Any violation stops the run with
`stop_reason: budget_exhausted` and `flow.run.failed` — never fail open.

## Node handlers

Node types map to pluggable handlers (`FlowHandlerRegistry`):

- `agent` — resolves the ref through the E2 Agent Registry (SemVer range),
  loads the handler from the installed plugin directory (or an in-process
  registration), and executes it through the Agent Runtime with its own
  fail-closed budgets. Token/cost metrics feed the flow budgets.
- `skill` / `tool` — resolved from an in-process `CallableRegistry` until
  Skills v2 (E6) provides a durable registry.
- `conditional` — pure routing; produces no output.
- `human` (E3-S4) — pauses the run for an operator decision (next section).
- `subflow`/`map` (E3-S5) — until that story lands, these types fail closed
  as `unsupported_node`.

## Human-in-the-loop (E3-S4)

A `human` node **pauses the run durably**: the step is persisted as
`waiting_human`, the run status becomes `waiting_human`, the cursor stays on
the node, the rendered prompt/form and optional expiry are stored as pause
metadata in the run state, and `flow.run.paused` is emitted. Because the
pause lives entirely in the store, it survives process restarts — any engine
instance on the same store can resume the run.

The decision cycle is API-first:

1. `GET /v2/flows/runs/{run_id}/pending-human` returns the pending request
   (node id, prompt, `form` schema, `expiresAt`) — 409 when the run is not
   waiting.
2. `POST /v2/flows/runs/{run_id}/human-decision` with
   `{"decision": {...}, "actor": "..."}` validates the decision against the
   node's `form` schema (422 on mismatch), records it as the human node's
   output, and resumes execution. The **actor** is recorded on the
   `flow.human.decision.recorded` event for auditability; it defaults to
   `"anonymous"` when omitted.

Human **edits alter run state**: a decision may carry
`edits: {<nodeId>: {...}}`; each patch merges into that node's recorded
output (`state.nodes.<id>.output`) before routing resumes, so downstream
predicates and bindings see the edited values. The human node itself is not
editable.

**Timeouts fail closed on the SLA**: when the node declares `timeoutSec`, the
pause records `expiresAt`. A late decision is rejected and the run is routed
through the node's `on: timeout` edge (the `onTimeout` route) instead of
resuming with the decision. `POST /v2/flows/human/expire` sweeps every due
wait (operator/cron surface — same no-daemon stance as cron triggers) and
returns the run ids routed through their timeout edges.

Authorization follows the platform's opt-in bearer token: when
`AUTODEV_API_TOKEN` is configured, unauthenticated decision calls are
rejected with 401. Full RBAC arrives with E11; the recorded actor is the
forward-compatible hook.

## Triggers

`api` starts (POST `/v2/flows/{ns}/{name}/runs`) are always allowed — the
Control Plane API is the platform entry point (§2.13). Every other trigger
must be **declared in the manifest** (fail closed): `message` and `webhook`
via POST `/v2/flows/{ns}/{name}/trigger`, `event` additionally matching the
subscribed event name, and `cron` via POST `/v2/flows/cron/tick`, which
evaluates every registered flow's 5-field cron schedules (no daemon — the job
queue or an operator ticks it). The normalized trigger document persists on
the run for auditability.

## Events

Ordered, durable, per-run (`domain.entity.action`, past tense):
`flow.run.started`, `run.step.started`, `run.step.completed`,
`run.step.failed`, `flow.run.paused`, `flow.human.decision.recorded`,
`flow.run.completed`, `flow.run.failed`. Until the Event
Bus (E9) exists, the event store is the authoritative log — the same E1
precedent as plugin lifecycle events — and is exposed at
GET `/v2/flows/runs/{run_id}/events`.

## API surface (`/v2/flows`)

| Method & path | Purpose |
| --- | --- |
| `POST /v2/flows` | Validate + register a flow definition (422 with all errors when invalid) |
| `POST /v2/flows/validate` | Validate without registering (used by editors/CI) |
| `GET /v2/flows` | Catalog of registered flows |
| `GET /v2/flows/{ns}/{name}` | Registered versions of one flow |
| `POST /v2/flows/{ns}/{name}/runs` | Start + execute a run (`input`, `versionRange`, `tenantId`) |
| `POST /v2/flows/{ns}/{name}/trigger` | Start through a declared trigger (message/webhook/event) |
| `POST /v2/flows/cron/tick` | Start every due cron run (optional `at` override) |
| `GET /v2/flows/runs/{run_id}` | Run document + ordered steps |
| `GET /v2/flows/runs/{run_id}/events` | The run's ordered event store |
| `GET /v2/flows/runs/{run_id}/pending-human` | Pending human request of a paused run (409 when not waiting) |
| `POST /v2/flows/runs/{run_id}/human-decision` | Record a decision/edits and resume (404/409/422 semantics) |
| `POST /v2/flows/human/expire` | Expire every due human wait through its timeout route |

Every payload carries `schemaVersion`. Authentication follows the platform's
opt-in bearer token (`AUTODEV_API_TOKEN`, `backend/api/security.py`).
