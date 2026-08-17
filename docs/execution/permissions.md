# Execution Policy Engine (E14-S2)

> Canonical decisions: RFC-010 (`docs/v2_platform/decisions/RFC-010-execution-policy-contract.md`)
> and ADR-022 (`docs/v2_platform/decisions/ADR-022-execution-policy-engine.md`).
> Story definition: `docs/v2_platform/phases/e14_real_execution_governance.md#e14-s2`.

## What changed

Every action `TaskExecutor` (E14-S1) dispatches is now gated by
`backend.execution.policy.PolicyService` before it reaches the runner. A
denied action never runs — it produces a `failed` `ExecutionResult` with
`error="policy denied: <reason>"` and no `execution.action.started` is
emitted (nothing started).

## Model

- **Categories**: `shell`, `fs-write`, `patch`, `network`, `secrets-read`,
  `validation`. `ACTION_TYPE_TO_POLICY_CATEGORY` maps every
  `ExecutionActionType` to its category; `network`/`secrets-read` have no
  action-type source yet.
- **Rules**: `category` + `effect` (`allow`/`deny`) + scope
  (`project`/`repository`/`session` + id) + an optional `pattern` glob
  matched against the action's first command token or file path.
- **Dynamic permissions**: the same shape as a rule, always `allow`,
  granted at runtime (E14-S3's hybrid "always" option) rather than
  configured ahead of time.
- **Decision**: `allowed` + `matched` (was any rule found at all?) +
  `reason`. `matched=False` is how E14-S3's hybrid mode tells "nothing
  covers this" apart from "explicitly denied."

## Precedence

When more than one rule matches an action, specificity wins before effect:

1. A dynamic permission with a pattern (highest — a deliberate, one-off
   human grant for exactly this command).
2. A static rule with a pattern.
3. A dynamic permission with no pattern.
4. A static rule with no pattern (lowest — e.g. a category-wide default).

Within the highest-scoring tier, an explicit `deny` wins over an `allow`
(fail-closed tie-break). This lets a hybrid-mode "always" grant for one
command carve an exception out of a broader static `deny`, while a
specific static `deny` still overrides a broader static `allow`.

## Fail-closed / local-first balance

A tenant with any stored rule is governed by exactly those rules — no
implicit fallback. A tenant with **no** stored rules:

- In production (`AUTODEV_PROFILE=prod`): `PolicyMissingError` — every
  evaluation for that tenant fails closed.
- Outside production: a permissive allow-all default across every
  category. This mirrors `QuotaService`'s already-accepted local-mode
  fallback (ADR-019) and keeps the platform's local-first guarantee intact
  — a policy engine that blocked everything locally by default would
  regress the Alpha gate's `test_local_first_mode.py`.

## REST surface

`GET /v2/execution/policy` (`policy:read`) — the tenant's effective rules.
`POST /v2/execution/policy` (`policy:admin`) — add one rule. Dynamic
permission list/revoke endpoints land with E14-S3, which is what actually
grants them.

## Scope boundary

Not built in this story: execution modes consuming `matched` to decide
pause-vs-deny (E14-S3), a Web UX to manage rules (E14-S5, though the CLI/API
already work), and `network`/`secrets-read` enforcement (no runner emits
those categories yet).
