# ADR-022: Execution Policy Engine

- **Status:** Accepted
- **Date:** 2026-08-17
- **Authors:** AutoDev platform team
- **Related epic:** E14
- **Supersedes/Relates to:** RFC-010, ADR-021 (E14-S1's `ExecutionAction`/`ExecutionResult` this gates)

## Context

E14-S1 shipped a real `TaskExecutor` with no gate — every derived action
executes unconditionally. E14-S2 is the story that closes that gap: "no
action without an explicit policy entry is permitted" (fail-closed) is the
story's headline functional criterion. `backend/quotas/` (ADR-019) already
established the accepted pattern for a per-tenant durable governance
resource in this codebase: production fails closed without a stored policy,
local/dev mode falls back to a finite/permissive default so the platform's
own Local-first principle (§2.13, verified by the Alpha gate's
`test_local_first_mode.py`) is not broken by an unconfigured governance
layer.

## Decision

Adopt `PolicyRule`/`PolicyDecision` (`backend/execution/policy.py`) as
described in RFC-010: category-scoped allow/deny rules, a `matched` field
distinguishing "no rule" from "explicit deny" (needed by E14-S3's hybrid
mode), a durable per-decision audit trail, and two additive events. Mirror
`QuotaService`'s resolution rule exactly:  a tenant with any stored rule
uses it; a tenant with none is fail-closed in production
(`PolicyMissingError`) and permissive outside production.

`TaskExecutor` gates every action through an optional injected
`PolicyEvaluator` before dispatch — `policy=None` (the default for direct
construction) preserves E14-S1's existing behavior;
`OrchestratorService.__init__` wires a real `PolicyService()`, so every
`execute_plan` call is gated from this story onward.

## Alternatives considered

1. **Default-deny even in local/dev mode** — rejected: this would make
   every `execute_plan` call fail out of the box for any local developer
   who has not first configured policy rules, directly regressing the
   Alpha gate's tested "local-first mode runs with no external
   dependencies" guarantee (the same trade-off ADR-019 already made and
   accepted for quotas).
2. **A single global allow/deny toggle per tenant instead of per-category
   rules** — rejected: too coarse to satisfy the story's functional
   criterion ("a project-scoped allow rule permits equivalent future
   actions") without collapsing every action type into one decision.

## Consequences

- **Positive:** execution actions are governed for the first time;
  E14-S3 (execution modes), E14-S4 (hardened runners), and E14-S5 (Web UX
  approval panel) all have a stable decision object to build on.
- **Negative / trade-offs:** local/dev mode stays permissive by default —
  an operator who wants fail-closed behavior locally must explicitly write
  rules (same trade-off already accepted for quotas); the `pattern` glob
  match is intentionally simple (matched against the action's first
  command token or file path) since today's derived actions are
  single-token commands (E14-S1's category heuristic) — richer pattern
  matching is deferred until a real need appears.
- **Contract impact:** additive only — no `hostApi`/SemVer bump, no schema
  migration.

## Rollback plan

No feature flag: revert `backend/execution/policy.py`, the
`TaskExecutor`/`OrchestratorService` wiring, the new router, and the two
event-catalog entries. No stored data to migrate back (new tables only,
empty until an operator writes rules).

## References
- RFC-010 (`RFC-010-execution-policy-contract.md`)
- ADR-019 (Multi-Tenant Isolation, Quotas, and Run Budgets) — the pattern mirrored here
- ADR-021 (Real Task Executor Contracts) — the contract this gates
