# E35 — Beta Readiness: Gates, Evidence & Runbooks

**Wave:** v2.0-beta — "plataforma completa em produção controlada".
**Status:** Not started · **Stories:** 0/3 complete
**Depends on:** E14 (real execution), E32 (isolation), E33 (secrets), E34
(install), E11 (observability/audit), E12 (quality gates)
**Enables:** an honest, testable v2.0-beta gate; GA readiness (E13)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.9
(v2.0-beta), §18.10; `docs/v2_platform/beta_gap_analysis.md`

## Objective

Turn the v2.0-beta gate from a claims checklist into an **evidence-backed
gate**: an expanded gate checklist (§18.9) whose new criteria (isolation,
secrets, clean install) are asserted from run records and test evidence —
not from configuration or self-report; a **Beta acceptance definition** for
the central coding flow (plan → code → patch → validate in sandbox →
evaluate) executed end to end under RBAC, budgets and traces; and an
**open-decisions & risk register** with the runbooks Beta operation needs.
The goal is not to declare SOTA coverage; it is to prove a complete coding
platform on the central flow, extensible without compromising safety,
predictability or quality.

## Key result

The v2.0-beta gate can be evaluated mechanically: each criterion maps to a
named evidence source (test, run record, audit trail); the acceptance flow
definition is executable as a checklist against a reference project; and
every pending architectural decision (ADR-013/014/015) is tracked with an
owner and an explicit "decided by" milestone instead of being silently
resolved.

## Stories

### E35-S1 — Expanded Beta gate & evidence mapping

Subtasks:
- `E35-S1-T1`: gate expansion — add to §18.9 v2.0-beta the criteria for
  isolated fail-closed execution (E32), no-plaintext secrets (E33) and
  clean-environment install (E34); each criterion phrased as an assertable
  statement.
- `E35-S1-T2`: evidence map — for every v2.0-beta criterion (existing and
  new), name the evidence source (test suite, run record field, audit
  event) in a gate table; criteria without an evidence source are flagged
  as gaps, not assumed.
- `E35-S1-T3`: fato vs recomendação discipline — gate documentation
  distinguishes observed fact (with evidence link) from recommendation,
  per the audit contract in `beta_gap_analysis.md`.

| Criterion | Detail |
| --- | --- |
| Functional | Every v2.0-beta gate criterion has a named evidence source or an explicit open gap; the new E32/E33/E34 criteria are present in §18.9 |
| Non-functional | Gate table maintained alongside progress.md (single source, no drift) |
| DoR (specific) | E32/E33/E34 phase docs approved; gap analysis published |
| DoD (specific) | §18.9 updated; evidence map committed in the gap analysis |
| Dependencies | E32, E33, E34 (definitions; execution not required to write the map) |

### E35-S2 — Beta acceptance flow (central coding flow, end to end)

Subtasks:
- `E35-S2-T1`: acceptance definition — a reference-project scenario
  covering plan → code → apply patch → validate in sandbox → evaluate,
  under RBAC, fail-closed budgets and end-to-end traces (the §18.9
  criterion 1), written as an executable checklist with expected typed
  outcomes per step.
- `E35-S2-T2`: negative paths — the acceptance definition includes denial
  paths (permission denied, budget exhausted, isolation violation, secret
  revoked) each ending in a typed, audited state.
- `E35-S2-T3`: gate rehearsal — a documented dry-run procedure of the full
  acceptance flow, producing the evidence bundle the gate consumes.

| Criterion | Detail |
| --- | --- |
| Functional | The acceptance checklist covers the central flow plus the four negative paths, each with a typed expected outcome; a rehearsal produces the gate evidence bundle |
| Non-functional | Checklist runnable by a non-author following the doc alone |
| DoR (specific) | E35-S1 evidence map; E14-S1 flow available |
| DoD (specific) | Acceptance doc committed; rehearsal procedure in runbooks |
| Dependencies | E35-S1, E14, E32, E33 |

### E35-S3 — Open-decisions register, risks & runbooks

Subtasks:
- `E35-S3-T1`: open-decisions register — ADR-013 (isolation backend),
  ADR-014 (secret store format), ADR-015 (install strategy) tracked with
  options, recommendation, owner and "decided by" milestone; no silent
  resolution.
- `E35-S3-T2`: risk register — Beta risks (isolation escape, secret leak,
  failed upgrade, runaway execution) with mitigations mapped to
  E32/E33/E34/E14 stories.
- `E35-S3-T3`: runbooks — Beta operational runbooks (incident on isolation
  violation, secret rotation under suspicion of leak, failed
  upgrade/restore) extending the E11 runbook set.

| Criterion | Detail |
| --- | --- |
| Functional | Every pending architectural decision appears in the register with owner and milestone; each Beta risk maps to a mitigating story; the three runbooks exist and reference real procedures |
| Non-functional | Register reviewed at each wave boundary (documented cadence) |
| DoR (specific) | ADR-013/014/015 filed |
| DoD (specific) | Register + risk table in `beta_gap_analysis.md`; runbooks under `docs/runbooks/` |
| Dependencies | E32, E33, E34, E11 |

## Contracts & decisions

- E35 introduces no new extension points; it governs evidence for existing
  ones. Gate criteria must reference E12 contract-test results where the
  criterion concerns an extension point.

## DoR / DoD

- **DoR:** gap analysis published; E32/E33/E34 phase docs approved.
- **DoD:** §18.9 expanded; evidence map, acceptance definition, registers
  and runbooks committed; no push/PR without explicit authorization.
