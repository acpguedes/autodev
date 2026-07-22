# E36 — SDD Operating Model & Document Authority

**Wave:** v2.3 — Platform Excellence (planning-only; starts after E20-S1/S2 are
stable, but its document-authority story can land immediately because it changes
planning discipline only).
**Status:** Not started · **Stories:** 0/4 complete
**Depends on:** E20, E21, E22, E23; document-authority story depends only on the
current docs tree.
**Enables:** consistent spec-driven execution across product modes, less drift
between architecture/progress docs, and a reviewable SDD posture competitive
with Spec Kit, Kiro, Tessl and large hosted coding agents.
**Canonical source:** this phase doc plus `docs/specs/sdd_operating_model.md`
(to be created by E36-S2). The architecture reference remains normative for
contracts; `progress.md` remains authoritative for implementation status.

## Objective

Turn spec-driven development from a set of related platform subsystems into an
explicit **operating model**. The platform must know which artifact authorizes
work, which gate blocks execution, when a waiver is permitted, how exploratory
prototypes become specs, and which document wins when planning documents drift.

## Key result

A contributor, agent, API client or UI flow can answer the same questions in a
machine-readable way: "May this work start?", "Which spec or waiver authorizes
it?", "Which acceptance gates define done?", "Which document is authoritative
for status?", and "Which drift record must be resolved before implementation?".

## Stories

### E36-S1 — Document authority and drift ledger

Subtasks:
- `E36-S1-T1`: add a concise document-authority table to `docs/v2_platform/README.md`,
  `docs/v2_platform/progress.md`, and the opening section of
  `docs/architecture/v2_platform_reference.md`.
- `E36-S1-T2`: define a `Doc drift` ledger section in `progress.md` for conflicts
  between the reference, phase docs, tracker, AGENTS.md and implementation evidence.
- `E36-S1-T3`: update agent workflow guidance so agents resolve status from
  `progress.md` and contracts from the reference/phase docs instead of making an
  implicit choice.

| Criterion | Detail |
| --- | --- |
| Functional | A contributor can identify the authoritative source for contracts, status, phase scope, ADR/RFC decisions and implementation evidence from any v2 entry point |
| Non-functional | The change is documentation-only and does not reorder work by itself |
| DoR (specific) | Current authority conflict reviewed |
| DoD (specific) | Tables present in all three docs; drift-ledger format documented |
| Dependencies | None |

### E36-S2 — SDD operating model artifact

Subtasks:
- `E36-S2-T1`: create `docs/specs/sdd_operating_model.md` covering greenfield,
  brownfield, hotfix, small-change and pre-spec prototype paths.
- `E36-S2-T2`: define machine-readable authorization states: `unscoped`,
  `prototype`, `spec_draft`, `approved_spec`, `waived`, `executing`,
  `verified`, `released`, `retro_required`.
- `E36-S2-T3`: link the model from E20-E24 phase docs and from Spec Studio UX
  so every surface follows one lifecycle.

| Criterion | Detail |
| --- | --- |
| Functional | A task without an approved spec or explicit waiver cannot enter governed execution; a hotfix waiver creates a retro-spec obligation |
| Non-functional | Prototype mode is time/cost bounded and cannot silently become production behavior |
| DoR (specific) | E20 lifecycle contract reviewed |
| DoD (specific) | Operating-model doc, state diagram and DoD links updated |
| Dependencies | E20, E21 |

### E36-S3 — Waiver, exception and retro-spec contract

Subtasks:
- `E36-S3-T1`: define waiver types (`small_change`, `incident_hotfix`,
  `pre_spec_prototype`, `external_patch`) with owner, reason, expiry and
  permitted gates.
- `E36-S3-T2`: require same-change coupling: behavior-changing code patches
  either link to a spec delta or to an active waiver that expires into a
  retro-spec task.
- `E36-S3-T3`: add negative tests to E22/E23 planning: unauthorized behavior
  changes block before execution or before merge, depending on gate tier.

| Criterion | Detail |
| --- | --- |
| Functional | A behavior-changing patch without spec delta or waiver is blocked and explains the missing authorization |
| Non-functional | Waivers are auditable, tenant-scoped and expire fail-closed |
| DoR (specific) | E22 drift gates scoped |
| DoD (specific) | Waiver schema and negative gate tests documented |
| Dependencies | E20, E22, E23 |

### E36-S4 — SDD fitness gates in CI and release readiness

Subtasks:
- `E36-S4-T1`: define CI-level checks for orphan requirements, orphan patches,
  expired waivers, generated-test tampering and unpublished spec edits.
- `E36-S4-T2`: add release-readiness output summarizing spec coverage,
  acceptance pass rate, drift status and waivers.
- `E36-S4-T3`: make the GA gate require a green SDD readiness report for the
  reference benchmark and at least one real project flow.

| Criterion | Detail |
| --- | --- |
| Functional | Release readiness is computed from registry/traceability data, not from prose claims |
| Non-functional | Checks are local-first and work with SQLite + stub provider where possible |
| DoR (specific) | E21 traceability and E22 gates available |
| DoD (specific) | CI-gate spec and release report format documented |
| Dependencies | E21, E22, E12 |

## Epic exit checklist

- [ ] All 4 stories meet the global DoD plus story-specific DoD above.
- [ ] The SDD operating model is linked from the v2 index, Spec phase docs and
      agent guide.
- [ ] `docs/v2_platform/progress.md` updated.
