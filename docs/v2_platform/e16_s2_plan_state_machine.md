# E16-S2 — Plan step-approval state machine

Status: implemented. Scope: `backend/api/routers/plan_approval_v2.py`,
`backend/plans/step_state.py`, event catalog additions in
`backend/events/catalog.py`.

## Why

The legacy plan document (`backend.plans.models.PlanDocument`) stores
`steps` as a plain `list[str]` with a single plan-level `status`
(`draft`/`approved`/`rejected`). There is no way to approve or edit one
step without deciding the whole plan. E16-S2 adds a step-granular
approval workflow on top of the same legacy plan content, versioned under
`/v2/plans`, without touching the legacy `/plans/{sessionId}` or
`/sessions/{id}/execution-plan` routers (still in place for existing
callers).

## State machine

Each step independently moves through:

```
draft --review--> under_review --approve--> approved --execute--> executing --complete--> completed
                        |
                        +--reject--> rejected
```

- `draft` and `under_review` are the only editable states (`PUT
  .../steps/{i}`).
- `rejected` and `completed` are terminal — no further action is legal.
- There is no dedicated "submit for review" endpoint in this story's
  scope: a step is auto-promoted from `draft` to `under_review` the first
  time it is read or acted upon (`GET`, `PUT` edit, `approve`, `reject`),
  emitting `plan.step.reviewing` with `actor: "system"`.
- Every edge not listed above (e.g. `approve` on an already-`approved`
  step, `execute` on a `rejected`/`under_review` step) is illegal and
  denied with `v2_error(400, ...)`.

A plan-level status is rolled up from its steps' states
(`rollup_plan_state` in `backend/plans/step_state.py`): `executing` if any
step is executing; `completed` only if every step is completed;
`rejected` if any step was rejected; `approved` if every non-completed
step is approved; `under_review` if any step has left `draft`; otherwise
`draft`.

## Storage and atomicity

Step state is tracked in an additive table (`plan_step_state`, keyed by
`(session_id, step_index)`, with a `tenant_id` column and a foreign key to
`plan_documents(session_id)` since E50-S3) managed by `StepApprovalStore`.
As of E55, the store runs on both SQLite and PostgreSQL through the shared
persistence contract (E49, ADR-025) — the same port pattern established for
`QuotaStore` (E51) and `SecretStore` (E52) — and every operation is
tenant-scoped, enforced by Row-Level Security on PostgreSQL (E50-S4). Prior
to E55 the store connected to SQLite directly and silently diverted to a
standalone file whenever `DATABASE_URL` was unset or PostgreSQL; that
fallback no longer exists (see `docs/config.md`'s
`AUTODEV_PLAN_STEP_STATE_DB` note and `docs/v2_platform/phases/e55_plan_step_state_postgres.md`).

Every read-check-write sequence (`update_content`, `delete_step`,
`transition`) is guarded by the backing connection's transaction —
`BEGIN IMMEDIATE` on SQLite, `SELECT ... FOR UPDATE` on PostgreSQL — and its
mutating `UPDATE`/`DELETE` is additionally conditioned on the exact state
just read (`WHERE ... AND state = ...`), so a transition that raced past a
concurrent one affects zero rows and is rejected outright rather than
silently overwriting the winner (E55-S2). This replaced a process-local
`threading.Lock()`, which protected nothing across replicas or separate
processes.

## Events

Every transition emits one of five `plan.step.*` events (E9-S3 bus,
`partition_key=session_id`, `tenant_id="default"`), sharing one payload
model (`PlanStepTransitionData`: `sessionId`, `stepIndex`, `fromState`,
`toState`, `actor`):

| Event                  | Fired on transition to |
|-------------------------|------------------------|
| `plan.step.reviewing`   | `under_review`         |
| `plan.step.approved`    | `approved`             |
| `plan.step.rejected`    | `rejected`             |
| `plan.step.executing`   | `executing`            |
| `plan.step.completed`   | `completed`            |

Emission is best-effort via `backend.events.runtime.emit_event` — a bus
failure never blocks an approval decision from taking effect.

## Endpoints

All under `/v2/plans`, RBAC-gated by the existing `require_v2_principal`
seam:

- `GET /v2/plans/{session_id}` — list steps with rolled-up plan status.
- `GET /v2/plans/{session_id}/steps/{step_index}` — read one step.
- `PUT /v2/plans/{session_id}/steps/{step_index}` — edit content
  (`draft`/`under_review` only).
- `POST /v2/plans/{session_id}/steps/{step_index}/approve` —
  `{actor, note?}`.
- `POST /v2/plans/{session_id}/steps/{step_index}/reject` —
  `{actor, note?}`.
- `POST /v2/plans/{session_id}/execute-approved` —
  `{step_indices?, actor?}`; executes only `approved` steps. Naming an
  index that is not `approved` (e.g. `rejected` or still `under_review`)
  is refused with 400. Omitting `step_indices` executes every currently
  `approved` step, or 400s if there are none.

## Reuse note for E14-S3 / E14-S5

The state names are intentionally generic, not tied to a single
execution mode, so E14-S3's three execution modes can drive the same
machine without a new model:

- **approval mode** (this story's default): a human calls `approve`/
  `reject` on each `under_review` step.
- **auto mode**: the orchestrator itself calls the same `transition`
  action (`approve`) immediately after a step reaches `under_review`,
  with `actor` set to the automation identity instead of a human's — no
  change to the state machine or its legal edges.
- **hybrid mode**: some steps are auto-approved, others wait for a human
  decision; both paths call the identical `transition("approve", ...)`
  edge, so the two policies compose without special-casing.

E14-S5 can therefore reuse `StepApprovalStore`/`StepState` as-is; only
the *caller* of `approve` differs per mode.
