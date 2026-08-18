# RFC-010: Execution Policy Contract

- **Status:** Accepted
- **Author(s):** AutoDev platform team          **Date:** 2026-08-17
- **Reviewers:** N/A (single-session review)
- **Epic(s):** E14                 **Stories:** E14-S2, E14-S3 (execution modes consume it)
- **Comment deadline:** 2026-08-17

## Summary

Introduce a fail-closed permission/policy contract — `PolicyRule` and
`PolicyDecision` — governing which `ExecutionAction`s (RFC-009) a tenant's
runs may actually perform, plus a durable per-decision audit trail and two
new events (`execution.policy.allowed`/`.denied`).

## Motivation

E14-S1 gave `TaskExecutor` a real runner with no gate: every action a task
maps to executes unconditionally. E14-S2 is the story that closes that gap
per the epic's own sequencing (E14-S3's execution modes, E14-S4's hardened
runners, and E14-S5's Web UX approval panel all depend on a policy decision
existing to react to).

## Proposed design

New module `backend/execution/policy.py`, mirroring
`backend/quotas/service.py` + `backend/quotas/store.py` (an already-accepted
pattern for a per-tenant durable resource: ADR-019):

- `PolicyCategory(StrEnum)`: `shell`, `fs-write`, `patch`, `network`,
  `secrets-read`, `validation`. `ACTION_TYPE_TO_POLICY_CATEGORY` maps every
  `ExecutionActionType` to its category (`create_file`/`edit_file` →
  `fs-write`, `apply_patch` → `patch`, `run_command` → `shell`,
  `run_validation` → `validation`); `network`/`secrets-read` are declared
  categories with no action-type source today (future runners set them,
  matching the precedent in `backend/plugins/permissions.py`, the closest
  existing category taxonomy in this codebase).
- `PolicyRule` (frozen dataclass): `category`, `effect` (`allow`/`deny`),
  `scope_kind` (`project`/`repository`/`session`) + `scope_id`, an optional
  `pattern` glob matched against the action's command/path.
- `PolicyDecision(allowed, matched, reason)` — `matched=False` (no rule
  found) is distinguished from an explicit deny so E14-S3's hybrid mode can
  tell "uncovered" apart from "denied."
- `PolicyStore`: its own SQLite tables (`execution_policy_rules`,
  `execution_dynamic_permissions` — the latter populated by E14-S3's hybrid
  "always" option, `execution_policy_decisions` — the audit trail).
- `PolicyService.resolve_rules(tenant_id)`: a tenant with any stored rule
  uses exactly those; a tenant with none, in production
  (`autodev_profile == "prod"`), raises `PolicyMissingError` (fail closed);
  outside production, falls back to a permissive allow-all default. This
  mirrors `QuotaService`'s already-accepted local-mode fallback and
  preserves the Alpha gate's tested "local-first mode runs with no external
  dependencies" guarantee — a policy engine that blocks every action by
  default in local/dev mode would silently break that guarantee.
- `PolicyService.evaluate(tenant_id, action, run_id, actor)`: resolves
  rules + dynamic permissions, matches by category (+ pattern; an explicit
  `deny` wins over a matching `allow` — fail-closed tie-break), durably
  records the decision, and emits `execution.policy.allowed`/`.denied`.

`TaskExecutor.execute()` (`backend/execution/executor.py`) gains an
optional `policy: PolicyEvaluator | None` constructor parameter. When set,
every derived action is evaluated before dispatch; a denied action never
reaches the runner (`ExecutionResult(status="failed", error="policy
denied: ...")`, no `execution.action.started` emitted since nothing ran).
`policy=None` preserves E14-S1's existing unguarded behavior for direct
`TaskExecutor` construction outside `OrchestratorService`.
`OrchestratorService.__init__` wires a real `PolicyService()`.

### Contracts and compatibility
- **API change:** new `/v2/execution/policy` router (`GET`/`PUT` rules,
  `GET`/`DELETE` dynamic permissions), scoped `policy:read`/`policy:admin`
  per the `resource:action` convention (`quota:read`/`quota:admin`
  precedent).
- **hostApi/SemVer change:** none — internal backend contract, not an SDK
  extension point.
- **Data migrations:** none — new tables only, created by `PolicyStore`
  the same way `QuotaStore` creates its own.

## Alternatives considered

1. **Extend the quota policy schema to also cover execution actions** —
   rejected: quotas are numeric ceilings (ADR-019), execution policy is
   categorical allow/deny; conflating them would make both schemas harder
   to reason about and version independently.
2. **No `matched` field, collapse to a plain boolean `allowed`** —
   rejected: E14-S3's hybrid mode needs to distinguish "no rule covers
   this" (pause and ask) from "explicitly denied" (fail, don't ask) — a
   plain boolean can't express that distinction.

## Impact

- **Security / RBAC / permissions:** this *is* the permission layer for
  execution actions; `policy:admin` is required to write rules, matching
  the RBAC role hierarchy already enforced globally (E11-S2).
- **Observability (traces/metrics/events):** two new event types; every
  decision durably audited (actor, reason, timestamp).
- **Cost / budgets / quotas:** unaffected — orthogonal to E11-S3's
  numeric quotas.
- **Accessibility (if UI):** N/A, backend-only story (E14-S5 builds the UI
  later).
- **Performance / SLOs:** in-memory/SQLite lookup per action, well under
  the story's 50ms NFR.

## Implementation and rollout plan

Single story (E14-S2), no feature flag — the fail-closed behavior only
activates in production for tenants with no stored rules, which is already
true of no tenant today (nothing writes `execution_policy_rules` yet), so
rollout is a no-op for existing deployments until an operator opts in by
writing rules.

## Open questions

None for S2's scope. E14-S3 will need to decide the exact pause/resume
persistence shape for a "pending" decision — noted as its own story, not
blocked on this RFC.
