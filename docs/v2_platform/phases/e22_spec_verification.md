# E22 — Spec Verification: Executable Acceptance & Drift Enforcement

**Wave:** v2.1 — Spec & Harness (after E20/E21; S1/S3 additionally gated on
E14-S4 sandbox runners and E12 contract-test/eval infrastructure).
**Status:** Not started · **Stories:** 0/5 complete
**Depends on:** E20, E21, E12 (evals & gates), E14-S1–S4 (executor + sandbox
runners), E7 (tree-sitter/static analysis)
**Enables:** E23 (verification gates are the harness's reward signal), E24-S4
(drift/coverage dashboards)
**Canonical source:** `docs/architecture/v2_platform_reference.md` §22.5,
§18.7.14; RFC-007

## Objective

Keep the spec authoritative **mechanically**, not by discipline: compile
acceptance criteria into runnable tests executed in the sandbox, link evals to
requirements, detect spec↔code drift by comparing an Intent Graph (from specs)
with an Evidence Graph (from static analysis) and block on divergence, couple
spec deltas to code patches in the same change, and surface human-legible
verification artifacts as the review surface.

## Key result

"Requirement satisfied" is a computed, evidence-backed state: its acceptance
scenarios pass as real tests in the sandbox, its eval thresholds hold, and no
drift gate is open — while a patch that changes spec'd behavior without a
matching spec delta is blocked (or waived explicitly, per gate tier).

## Prior art (condensed)

CodeMySpec (BDD scenarios as enforced gates, live-app QA), Tessl (tests
generated from spec examples), arXiv 2606.27045 "Spec Growth Engine"
(Intent/Evidence graph drift enforcement, same-commit coupling, HARD/SOFT/AUTO
tiers), Antigravity (verification artifacts as the trust surface). Full
comparison and sources in RFC-007.

## Stories

### E22-S1 — Acceptance-criteria compiler

Subtasks:
- `E22-S1-T1`: compile `acceptance[]` scenarios (Given/When/Then, bound to EARS requirements) into runnable test cases for the project's stack (initial target: pytest for Python projects; the compiler is a pluggable `skill`).
- `E22-S1-T2`: execute compiled tests through the E14-S4 validation runner (sandboxed, no network by default); structured results (pass/fail per scenario, output, duration) persisted and linked to requirement IDs (E21-S4 edges).
- `E22-S1-T3`: generation stamps on emitted test files (`GENERATED FROM SPEC — DO NOT EDIT` + spec/requirement/version) so hand edits are detectable.

| Criterion | Detail |
| --- | --- |
| Functional | An acceptance scenario compiles to a test that fails before implementation and passes after; results attach to the requirement in the traceability graph; a hand-edited generated test is flagged |
| Non-functional | Compilation deterministic for a frozen spec version; tests run only in the sandbox (fail closed without Docker, inheriting E14-S4 semantics) |
| DoR (specific) | E20 `acceptance[]` contract stable; E14-S4 validation runner available |
| DoD (specific) | Red→green lifecycle test; stamp-tamper test; `docs/specs/acceptance.md` |
| Dependencies | E20-S1, E21-S4, E14-S4 |

### E22-S2 — Spec-linked evals

Subtasks:
- `E22-S2-T1`: extend the `eval.yaml` target vocabulary with requirement refs (`target: {type: requirement, ref: <spec-id>#R-<n>}`) — additive MINOR change to RFC-005's contract, recorded in the epic ADR.
- `E22-S2-T2`: acceptance gates — a requirement's "satisfied" state requires its linked eval thresholds to hold (deterministic and/or llm-judge rubrics per RFC-005).
- `E22-S2-T3`: eval results flow into the E21-S4 traceability edges (requirement↔eval-result).

| Criterion | Detail |
| --- | --- |
| Functional | An eval targeting `spec#R-3` runs through the existing `EvaluationService` and its result is queryable from the requirement's trace; a failing threshold marks the requirement unsatisfied |
| Non-functional | No fork of the eval engine — one execution path for agent-, flow-, and requirement-targeted evals |
| DoR (specific) | RFC-005/ADR-009 reviewed; additive target change agreed in epic ADR |
| DoD (specific) | Contract tests for the new target type; `docs/specs/evals.md` |
| Dependencies | E20-S1, E21-S4, E12, E5-S3/S4 |

### E22-S3 — Drift detection: Intent Graph vs Evidence Graph

Subtasks:
- `E22-S3-T1`: Intent Graph builder — nodes/edges declared by specs (components, public contracts, declared dependencies).
- `E22-S3-T2`: Evidence Graph builder — the same shape extracted from code via the E7 tree-sitter registry (modules, exported symbols, import edges).
- `E22-S3-T3`: drift report + blocking `validation_gate` plugin — orphan code (implemented-but-unspec'd), ghost specs (spec'd-but-unimplemented), undeclared dependencies, boundary-crossing imports; gate verdicts per tier (S4).

| Criterion | Detail |
| --- | --- |
| Functional | Removing a spec'd module from code (or adding an undeclared cross-boundary import) produces a drift finding; with the gate enabled at HARD tier the validation fails closed |
| Non-functional | Full-project drift check < 60 s on a 100k-LOC repo (incremental via the E7 index); findings carry file/spec locations |
| DoR (specific) | E20 design/contract fields sufficient to derive the Intent Graph; E7 language coverage documented (Python-first, like E7-S1) |
| DoD (specific) | Drift-fixture tests per finding type; gate contract test; `docs/specs/drift.md` |
| Dependencies | E20-S1, E7-S1, E12-S2 (gate contract) |

### E22-S4 — Same-change spec+code coupling & gate tiers

Subtasks:
- `E22-S4-T1`: patch-workflow rule — a patch touching code owned by a spec requires a matching spec delta (E20-S3 proposal) in the same change, or an explicit recorded waiver.
- `E22-S4-T2`: gate tiers by blast radius — HARD (public contract changes: block), SOFT (internal design: warn + require ack), AUTO (leaf/no-contract changes: pass with log) — configurable per project; the anti-ceremony escape hatch for trivial changes is the AUTO tier, not bypassing the system.
- `E22-S4-T3`: waiver audit — every waiver recorded with actor, reason, and scope; queryable via `/v2`.

| Criterion | Detail |
| --- | --- |
| Functional | A patch on spec-owned code without a delta is blocked at HARD tier and warned at SOFT; a waiver unblocks exactly one change and is auditable |
| Non-functional | Tier evaluation deterministic from the Intent Graph ownership map; no silent waivers |
| DoR (specific) | E22-S3 ownership/graph data available; E14 patch runner path reviewed |
| DoD (specific) | Tier matrix tests (3 tiers × with/without delta × waiver); `docs/specs/gates.md` |
| Dependencies | E22-S3, E20-S3, E14-S1/S4 |

### E22-S5 — Verification artifacts (human-legible evidence)

Subtasks:
- `E22-S5-T1`: verification-artifact model — per run/requirement: diffs, test results, eval scores, drift findings, and optional screenshots/recordings, stored via the Artifact Store (E8-S3) and linked in the traceability graph.
- `E22-S5-T2`: optional browser-in-the-loop runner — a sandboxed runner that drives the project's app (Playwright-class) to exercise acceptance scenarios end to end and captures evidence; strictly opt-in per project.
- `E22-S5-T3`: `/v2` read surface for an evidence bundle per requirement/run (the review payload E24-S4 renders).

| Criterion | Detail |
| --- | --- |
| Functional | A completed verification produces an evidence bundle a human can review without reading raw logs; browser evidence (when enabled) attaches screenshots to the scenario that produced them |
| Non-functional | Evidence immutable once attached; browser runner inherits sandbox permissions (no network beyond the app under test by default) |
| DoR (specific) | E8-S3 artifact pointers available (T2 gap closed or scoped around); E22-S1 result model stable |
| DoD (specific) | Evidence-bundle contract test; opt-in browser-runner test on a sample app; `docs/specs/evidence.md` |
| Dependencies | E22-S1, E8-S3, E14-S4 |

## v1/v2 precursor / starting point

- Validation Gates and the `SandboxRunner` exist (v1 precursor, formalized by
  E14-S4) — E22 reuses them as executors; nothing here spawns a second
  execution path.
- The `EvaluationService` (E5-S3/S4) is reused as-is; E22-S2 only widens the
  target vocabulary.
- There is no drift detection, no acceptance-criteria compilation, and no
  spec-coupled patch rule anywhere today — S1/S3/S4 start from zero on logic
  but sit entirely on existing seams (skill plugin, validation_gate plugin,
  patch workflow).

## Epic exit checklist

- [ ] All 5 stories meet the global DoD plus story-specific DoD above.
- [ ] Contract tests green for the acceptance compiler, requirement-targeted
      evals, the drift gate, and the evidence bundle.
- [ ] Epic ADR (drift model, gate tiers, eval-target extension) filed before
      E22-S1 implementation starts.
- [ ] `docs/v2_platform/progress.md` updated.
