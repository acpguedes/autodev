# Flow Engine — Execution, Durable State, Triggers, and Events

> Delivered by **E3-S2** (graph execution with durable Run/Step state).
> Manifest contract: `docs/flows/spec.md`. Implementation:
> `backend/flows/engine.py` (executor), `backend/flows/state.py` +
> `backend/flows/records.py` (durable Run/Step/Event store),
> `backend/flows/registry.py` (versioned definitions),
> `backend/flows/handlers.py` (node handlers),
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

Manifest budgets are enforced between activations and re-checked once more
before a run completes: wall clock, accumulated tokens, and accumulated cost
(agent nodes report the E2 runtime's metrics). An engine-level step cap
(default 1000 activations per run) additionally bounds guarded loops that
never exit. Any violation stops the run with `stop_reason: budget_exhausted`
and `flow.run.failed` — never fail open. `start_run`/`execute_run` accept an
optional `budget_cap` (used by composite nodes, ADR-006): the engine enforces
the element-wise minimum of the manifest budgets and the cap, and persists the
cap in the run state so resumed executions keep the same limits.

## Node handlers

Node types map to pluggable handlers (`FlowHandlerRegistry`):

- `agent` — resolves the ref through the E2 Agent Registry (SemVer range),
  loads the handler from the installed plugin directory (or an in-process
  registration), and executes it through the Agent Runtime with its own
  fail-closed budgets. Token/cost metrics feed the flow budgets.
- `skill` / `tool` — resolved from an in-process `CallableRegistry` until
  Skills v2 (E6) provides a durable registry.
- `conditional` — pure routing; produces no output.
- `subflow` / `map` — composite nodes (E3-S5), see the next section.
- `human` (E3-S4) — until that story lands, this type fails closed as
  `unsupported_node`.

## Composite nodes: sub-flow and map/reduce

Delivered by **E3-S5** (`backend/flows/composite.py`). Both node types
reference a **flow** (`ref` resolved through the flow registry with SemVer
ranges) and start real child runs linked to the parent via `parent_run_id`
(queryable with `FlowRunStore.list_runs(parent_run_id=...)`; child trigger
documents record `{type: subflow|map, parentRunId, nodeId}`).

- **`subflow`** executes the referenced flow synchronously as a child run,
  with the node's rendered input bindings as the child's run input. The node
  output is the child's consolidated output spread at the top level plus the
  reserved key `childRunId` (which always wins on collision), so downstream
  bindings stay ergonomic: `{{ nodes.sub.output.<field> }}`. The child's
  accumulated token/cost metrics charge the parent's budget ledger. A failed
  child fails the parent step closed, preserving `budget_exhausted` when that
  was the child's stop reason.
- **`map`** evaluates `over` against the run state; the result must be a list
  (anything else fails closed). It fans the referenced flow out one child run
  per item on a thread pool bounded by `maxParallel` (default 4). Map-node
  input bindings are rendered **per item by the handler** — the `item` root is
  bound to the current element (e.g. `{"value": "{{ item }}"}`); the engine's
  pre-rendered input is ignored for map nodes. `reduce: collect` (the only
  mode so far) aggregates ordered outputs — input order, not completion
  order — into `{"items": [...], "count": N, "childRunIds": [...]}`. Any
  branch failure skips the remaining branches and fails the step closed.
- **Budget propagation (ADR-006):** each child runs under a budget cap equal
  to the parent's remaining budget at spawn (`min` with the child's own
  manifest budgets; wall clock inherits the parent's remaining time). Map
  re-checks aggregate consumption before every launch and after every
  completion, failing the step with `budget_exhausted` on breach. See
  `docs/v2_platform/decisions/ADR-006-budget-propagation.md`.
- **Depth cap:** composite nesting is bounded at 16
  (`MAX_COMPOSITE_DEPTH`); exceeding it — e.g. a recursive sub-flow — fails
  closed with a clear error.

Hierarchical tracing: parent step outputs carry `childRunId(s)` (persisted in
the step record and in `nodes.<id>.output`), and every child run keeps its own
Run/Step/Event records under its `run_id` with `parent_run_id` linkage.

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
`run.step.failed`, `flow.run.completed`, `flow.run.failed`. Until the Event
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

Every payload carries `schemaVersion`. Authentication follows the platform's
opt-in bearer token (`AUTODEV_API_TOKEN`, `backend/api/security.py`).
