# E46 — Execution Failure Classification & Self-Repair Governance

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E43: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/3
**Depends on:** E14/E32 (execution + sandbox where failures originate),
E41-S5 (the self-repair loop being governed), E43-S1 (the `cd` sandbox
fix — which proved the *class* of problem but did not add classification)
**Enables:** self-repair that spends LLM calls only on failures a code
change can actually fix. Today any failed validation with written files
triggers a Coder repair — including sandbox policy rejections, missing
dependencies, and environment errors, where "repairing" risks rewriting
**correct** code and burning one LLM call + re-execution per failed
command.
**Canonical source:** two independent external code analyses
(2026-08-21), re-verified against the current tree (`943845f` + E43-S8
merge): `_maybe_self_repair` (`backend/orchestrator/service.py:1346-1454`)
gates only on failed status + files written; `ExecutionResult`
(`backend/execution/contracts.py:70-110`) carries no failure
classification; zero `failure_kind`-like fields exist in
`backend/execution/` or `backend/orchestrator/`. The E42/E43 live runs
demonstrated the blast radius: 10/10 validation tasks failed on a policy
rejection (`Command 'cd' is not in the allowed list`) and E41-S5's retry
loop reported `failed_after_retry` even though the generated code was
correct — E43-S1 fixed that one parser bug, but the next
policy/environment failure will misfire self-repair identically.

## Objective

Give execution results a typed failure taxonomy at the point where
failures originate, and make the self-repair policy consume it. Repair
becomes a governed decision ("this failure is repairable by changing
code") instead of a reflex ("something failed and files exist").

## Key result

A run whose validation fails for a non-code reason (policy denial,
command not allowed, environment unavailable, missing dependency)
completes with a clear typed outcome and **zero** repair LLM calls; a
genuine test failure still triggers the existing bounded repair, at most
once per dispatch batch.

## Stories

### E46-S1 — Failure taxonomy on ExecutionResult

Subtasks:
- `E46-S1-T1`: author **ADR-023 — Execution failure classification
  taxonomy** (kinds: `code_failure`, `command_not_allowed`,
  `policy_denied`, `environment_unavailable`, `dependency_missing`,
  `timeout`, `internal_error`; plus the derived
  `repairable_by_code_change: bool`). Additive, optional-with-default
  fields so existing producers/consumers keep working.
- `E46-S1-T2`: add the fields to `ExecutionResult`
  (`backend/execution/contracts.py`) and thread them through the
  `execution.action.*` event payloads (append-only event-schema
  extension, same discipline as E43-S2).
- `E46-S1-T3`: set the classification at the origins: the sandbox
  runner's allowlist/policy rejections (`backend/validation/sandbox.py`),
  environment provisioning failures (E32 backends), executor timeouts,
  and process exit codes (non-zero exit of an allowed command defaults
  to `code_failure`).

| Criterion | Detail |
| --- | --- |
| Functional | Every `ExecutionResult` produced by the sandbox/executor carries a `failure_kind` when failed; success results carry none |
| Non-functional | Additive contract — untouched callers keep working; events remain append-only compatible |
| DoR (specific) | ADR-023 drafted with the kind list above |
| DoD (specific) | Unit tests per origin: allowlist rejection → `command_not_allowed`; provision failure → `environment_unavailable`; failing test command → `code_failure` |
| Dependencies | E14, E32 |

### E46-S2 — Gate self-repair on repairable failures

Subtasks:
- `E46-S2-T1`: `_maybe_self_repair` fires only when the triggering
  failure is `repairable_by_code_change` (i.e. `code_failure`); all
  other kinds skip repair.
- `E46-S2-T2`: a skipped repair emits a typed event carrying the
  failure kind and skip reason (append-only event-catalog addition), so
  the timeline shows *why* no repair ran instead of silence.
- `E46-S2-T3`: unclassified/legacy results (no `failure_kind`) keep
  today's behavior during rollout — the gate fails open to the current
  reflex only for results that predate classification, and this is
  removed once all origins classify (tracked in the story DoD).

| Criterion | Detail |
| --- | --- |
| Functional | Policy/environment failures complete without invoking the Coder; genuine code failures still repair exactly as E41-S5 defined |
| Non-functional | Zero repair LLM calls on non-code failures (assertable via the StubLLMProvider call log) |
| DoR (specific) | E46-S1 landed |
| DoD (specific) | Test: run with an allowlist-rejected command → no Coder invocation + skip event; run with a failing test → repair still happens |
| Dependencies | E46-S1, E41-S5 |

### E46-S3 — Batched repair policy

Subtasks:
- `E46-S3-T1`: aggregate all repairable failures from one dispatch batch
  and run **at most one** repair pass over them (one Coder call with all
  failing evidence), instead of up to one repair per failed command.
- `E46-S3-T2`: after a repair, re-run only the validations that failed
  (or whose inputs the repair touched), not the full batch.

| Criterion | Detail |
| --- | --- |
| Functional | Multi-failure batches converge with a single repair attempt; repair remains bounded (no new retry loop beyond E41-S5's single attempt) |
| Non-functional | Repair LLM calls per batch ≤ 1; re-executions limited to affected validations |
| DoR (specific) | E46-S2 landed |
| DoD (specific) | Test with ≥ 3 failing validations asserting exactly one repair call and selective re-execution |
| Dependencies | E46-S2 |

## Contracts & decisions

- ADR-023 owns the taxonomy; the field set is additive to
  `ExecutionResult` and the `execution.action.*` event schema
  (append-only, per the E43-S2 precedent).
- Classification happens **at the failure origin** (sandbox/executor/
  environment manager), never by pattern-matching stderr in the
  orchestrator — the orchestrator only consumes the typed field.
- Explicit non-goals: expanding the number of repair attempts, new
  repair strategies, or auto-relaxing sandbox policy when
  `command_not_allowed` occurs (surfacing it is the fix; loosening
  policy is a human decision).

## DoR / DoD

- **DoR:** ADR-023 drafted; evidence anchors re-checked against HEAD at
  implementation start.
- **DoD:** all story DoDs met; the "0 repair calls on non-code failure"
  property is a test, not an observation;
  `docs/v2_platform/progress.md` updated; no push/PR without explicit
  authorization.
