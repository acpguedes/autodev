# Beta Acceptance Flow — Central Coding Flow, End to End (E35-S2)

> Story definition: `docs/v2_platform/phases/e35_beta_readiness_gates.md#e35-s2`.
> This is the executable checklist `docs/v2_platform/beta_gap_analysis.md`
> §11 cites as the composed rehearsal for gate criterion (1) — every step
> below is individually evidenced elsewhere in the codebase; this document
> is what strings those pieces into one scenario, not a new test suite.

## Purpose

Defines the v2.0-beta gate's central-flow acceptance criterion (§18.9,
criterion 1) as a scenario a non-author can run: **plan → code → apply
patch → validate in sandbox → evaluate**, under RBAC, fail-closed budgets,
and end-to-end traces — plus the four negative paths that prove those
controls actually stop something rather than only existing in configuration.

## Preconditions (reference project)

1. A reference git repository checked out locally (any small repo with a
   failing or improvable test works; `AGENTS.md`-style repos are not
   required).
2. `autodev bootstrap` (E34-S2) has been run and reports `"status": "ok"`.
3. A tenant with an RBAC principal that has the `VIEWER` role only (used in
   negative path N1) and a second principal with `ADMIN`/execution scopes
   (used for the happy path and N2–N4).
4. A quota policy set narrow enough to exhaust deliberately for N2:
   `autodev quotas set <tenant_id> --max-run-tokens 1 ...` (or an
   equivalently tight ceiling).
5. The isolated execution environment backend resolved (default
   `hardened_container`, E32) with a network policy that denies the
   destination used in N3.
6. A secret created via `autodev secrets create` (E33-S1, value via stdin)
   referenced by the reference project's execution profile, so it can be
   revoked in N4.

> **Profile constraint (added 2026-08-21, updated 2026-08-26).** This
> rehearsal is currently executable only under `AUTODEV_PROFILE=local`
> (SQLite). Preconditions 4, 5, and 6 — quotas, the execution environment
> backend, and secrets — and negative path N1 (`PolicyStore`) no longer
> depend on a SQLite-only store: `QuotaStore` (E51), `SecretStore` (E52),
> `PolicyStore` (E53), and `EnvironmentStore` (E54) all run on both backends
> via the E49 contract and no longer raise `ValueError` on a
> `postgresql://` `DATABASE_URL`. Running this flow in `prod` end to end is
> gated on the remaining E48-E60 program work (`postgres_production_completeness.md`),
> after which E57-S3 executes it in CI against a real `prod` stack. Stated
> here rather than left implicit, per the E35-S1-T3 fact-vs-recommendation
> discipline.

## Happy path

Each step names the action, the typed expected outcome, and the durable
evidence (event type, from `backend/events/catalog.py`, or a trace span)
that proves it happened — not a claim, an artifact to go look at.

| # | Step | Action | Expected typed outcome | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Plan | `autodev plan "<goal>"` (or `POST /v2/sessions/{id}/turns`) | A session with a derived plan; each step in `draft` state | `plan.step.added`; `GET /v2/sessions/{id}` |
| 2 | Approve (RBAC) | Reviewer principal approves a plan step via `POST /v2/plans/{session_id}/steps/{step_index}/approve` (E16-S2, `backend/api/routers/plan_approval_v2.py`) | Step transitions `under_review → approved`; denied for a principal without the `plan:approve` scope | `plan.step.approved`; `access.request.denied` (403) for the under-scoped attempt — see N1 |
| 3 | Code / apply patch | `autodev run execute-plan <session_id>` derives a patch from the approved step and applies it via the E0 patch engine | Patch applied to the workspace; changed-files list available for review | `patch.changedfiles.listed`, `patch.applied`; `run.timeline.patch` |
| 4 | Validate in sandbox | The same execution provisions an isolated environment (E32) and runs the project's validation command inside it | Environment provisioned with the resolved backend/profile; validation gate passes or fails with a typed reason; environment retired after | `environment.instance.provisioned`, `execution.action.started/completed`, `validation.gate.passed`\|`validation.gate.failed`, `environment.instance.retired`; `run.timeline.validation` |
| 5 | Evaluate | The reference eval (`autodev eval run`, E12-S3) scores the resulting patch | A scored eval result persisted and queryable | `eval.run.completed` |
| 6 | Traces | Every step above emits a correlated span | Spans share `autodev.run_id`; no step is missing a span | `backend/tests/unit/observability/test_observability.py::test_orchestrator_agent_step_emits_correlated_span` (pattern reused per-run) |
| 7 | Budgets | Steps 1–5 stay under the tenant's configured budget | No `QuotaExceededError`/budget-stop raised | Absence of `budget_exhausted` in the run's stop reason |

## Negative paths

Each negative path must end in a **typed, audited state** — not a silent
skip and not an unhandled exception.

| # | Scenario | Trigger | Expected typed outcome | Evidence |
| --- | --- | --- | --- | --- |
| N1 | Permission denied | The `VIEWER`-only principal from precondition 3 attempts step 2 (plan-step approval) | `403` with `access.request.denied` durably audited (ADR-018); the plan step stays `under_review` | `backend/api/authorization.py::enforce_control_plane_access`; `backend/tests/unit/api/test_rbac_v2.py` |
| N2 | Budget exhausted | Precondition 4's narrow quota is hit during step 3/4 | `QuotaExceededError` raised fail-closed; the run stops with reason `budget_exhausted`, prior completed steps remain persisted | `backend/quotas/contracts.py::QuotaExceededError`; `backend/tests/unit/quotas/test_service.py` |
| N3 | Isolation violation | The validation command in step 4 attempts the network destination precondition 5 denies | `environment.access.denied` recorded before the attempt is blocked; the environment is not torn down uncleanly — it retires normally with the denial on record | `backend/environments/manager.py`; `backend/tests/unit/environments/test_manager.py` |
| N4 | Secret revoked | Precondition 6's secret is revoked (`autodev secrets revoke`) before step 4 re-provisions | The revoked reference is **skipped** at the injection boundary (the environment still provisions; the secret is simply absent from its env) rather than failing the whole run; a direct `SecretStore.resolve()` call for that reference still raises `SecretRevokedError` (fails closed for any caller that isn't the injection path) | `backend/secret_store/contracts.py::SecretRevokedError`; `backend/tests/unit/environments/test_manager.py`; `backend/tests/unit/secret_store/test_service.py` |

## Rehearsal / dry-run procedure (E35-S2-T3)

An operator (not necessarily the story's author) can produce the gate
evidence bundle for a release candidate:

```bash
# 0. Preflight
autodev doctor
autodev bootstrap

# 1-2. Plan + approve
autodev plan "improve test coverage for module X"
# (as the reviewer principal, approve the derived step:)
curl -s -X POST "$BASE_URL/v2/plans/$SESSION_ID/steps/0/approve" \
  -H "Authorization: Bearer $REVIEWER_TOKEN" \
  -H "Content-Type: application/json" -d '{}'

# 3-5. Execute (code, validate, evaluate) in one call
autodev run execute-plan $SESSION_ID
autodev eval run evals/reference/agent_smoke/eval.yaml  # or the project's own eval set

# Evidence bundle: session/run state + tenant access-audit trail
curl -s "$BASE_URL/v2/sessions/$SESSION_ID" -o session.json
curl -s "$BASE_URL/v2/sessions/$SESSION_ID/runs" -o runs.json
curl -s "$BASE_URL/v2/audit/access?limit=200" -o access-audit.json
```

`session.json`, `runs.json`, and `access-audit.json` together are the
evidence bundle: every row in the Happy path / Negative path tables above
should have at least one matching entry (run results carry the
`execution.action.*`/`environment.*`/`validation.*`/`patch.*` event trail;
`access-audit.json` carries the `access.request.*` decisions). There is no
automated "gate pass/fail" verdict computed from the bundle — a human (or a
future E35 follow-up) reviews it against this checklist, consistent with
§18.9's "not from configuration or self-report" requirement.

For the negative paths, repeat the relevant step with the trigger condition
active (under-scoped principal, exhausted quota, denied network
destination, revoked secret) and confirm the matching row's evidence
appears instead of the happy-path row's.

## Scope reduction (stated, not hidden)

- This is a **documented procedure**, not a new automated test. The
  individual pieces (RBAC, budgets, isolation, patch/validation/eval) each
  already have unit/integration test coverage cited above; composing them
  into one live rehearsal against a real reference project is an operator
  action, not something this story adds to CI. Automating the rehearsal
  itself (a scripted "gate runner") is reasonable follow-up work, not
  required by this story's DoD (`docs/v2_platform/phases/e35_beta_readiness_gates.md`).
- No new REST endpoint was added for "evidence bundle export" — the
  commands above reuse existing `/v2/runs/{id}/events` and `/v2/audit`
  surfaces.
