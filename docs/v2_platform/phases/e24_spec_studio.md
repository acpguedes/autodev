# E24 — Spec Studio: AI-Assisted Spec Builder (UI)

**Wave:** v2.1 — Spec & Harness (UI epic of the wave; strictly after the E20–E23
API surfaces it consumes, and on top of the E15–E17 shell/screens).
**Status:** Not started · **Stories:** 0/5 complete
**Depends on:** E15–E17 (shell, `/v2` enablement, Control Center screens),
E20–E23 (the APIs every screen consumes)
**Enables:** the end-to-end operator experience of the v2.1 wave; E25 shares
its authoring patterns
**Canonical source:** `docs/architecture/v2_platform_reference.md` §22.7,
§18.7.16; RFC-007

## Objective

Give the spec-driven layer its operator surface — the "builder" — inside the
Control Center: a constitution wizard, an AI-assisted spec editor (EARS assist,
clarify loop, multi-variant plan comparison), a task board rendering the
dependency graph and waves with approval gates, traceability/drift dashboards
with the verification-evidence review surface, and a visual harness composer.
Authoring is itself AI-assisted by platform agents — the platform uses its own
agent framework to help write its specs.

## Key result

An operator can take a project from empty to executing without leaving the UI:
write the constitution with the wizard, author a spec with EARS assistance and
resolve ambiguities through a clarify loop, approve the compiled design/task
graph on the task board, watch harness runs flip requirement gates on the
dashboards, and review evidence bundles — all exclusively through `/v2`
(API-first, §2.13).

## Prior art (condensed)

Kiro (spec panes + approval dropdowns), Spec Kit (`/clarify`, multi-variant
plans), Antigravity (artifact-centric review surface). Full comparison and
sources in RFC-007.

## Stories

### E24-S1 — Constitution wizard & steering editor

Subtasks:
- `E24-S1-T1`: guided wizard — stack choices, conventions, non-negotiables — producing a valid constitution document (E20-S1 schema).
- `E24-S1-T2`: steering editor with linting (size bound, imperative-rule hints) and version history.
- `E24-S1-T3`: interop panel — preview/trigger the `AGENTS.md`/`CLAUDE.md` export (E20-S4-T3).

| Criterion | Detail |
| --- | --- |
| Functional | Wizard output validates against `constitution.schema.json`; edits create new versions (never mutate published); export preview matches the rendered file |
| Non-functional | WCAG 2.2 AA; all reads/writes via `/v2/specs` constitution endpoints |
| DoR (specific) | E20-S1/S4 available; E15 shell patterns reviewed |
| DoD (specific) | UI e2e test (wizard→publish→export); a11y audit; docs |
| Dependencies | E20-S1, E20-S4, E15, E17 |

### E24-S2 — Spec editor: EARS assist & clarify loop

Subtasks:
- `E24-S2-T1`: spec editor with EARS-aware assistance — an authoring agent proposes well-formed `WHEN … THE SYSTEM SHALL …` clauses from free-text intent; malformed clauses flagged inline via schema validation.
- `E24-S2-T2`: clarify loop — the agent asks targeted questions about ambiguities/gaps (uncovered edge cases, missing acceptance scenarios) before the spec can be submitted for review.
- `E24-S2-T3`: multi-variant comparison — render N compiler design variants (E21-S2-T3) side by side for selection.

| Criterion | Detail |
| --- | --- |
| Functional | Free-text intent becomes valid EARS clauses the author can accept/edit; submission is gated on the clarify loop completing (or being explicitly waived); variant selection feeds the approval flow |
| Non-functional | Authoring agent runs are ordinary traced agent runs (budgeted, inspectable); editor state autosaves as drafts |
| DoR (specific) | E20-S2 lifecycle + E21-S2 variants available |
| DoD (specific) | e2e authoring test incl. clarify gate; docs |
| Dependencies | E20-S2, E21-S2, E17 |

### E24-S3 — Task board: dependency graph, waves & approval gates

Subtasks:
- `E24-S3-T1`: task-graph view — dependency DAG with wave grouping, per-task requirement links, and status.
- `E24-S3-T2`: approval actions per phase (requirements → design → tasks) reusing the E17 plans screen interaction model and the E16-S2 state machine.
- `E24-S3-T3`: launch/monitor compiled runs from the board (deep-link into the E17 run/chat views).

| Criterion | Detail |
| --- | --- |
| Functional | The board renders the E21 graph faithfully (cycle-free, waves ordered); approving a phase transitions the E16-S2 state machine; a running task links to its live run view |
| Non-functional | Board usable at 200+ tasks (virtualization); WCAG 2.2 AA |
| DoR (specific) | E21-S2/S3 available; E17 plans screen patterns reviewed |
| DoD (specific) | e2e approve→execute test; a11y audit; docs |
| Dependencies | E21, E16-S2, E17 |

### E24-S4 — Traceability, drift & evidence dashboards

Subtasks:
- `E24-S4-T1`: coverage dashboard — requirements satisfied/unsatisfied/uncovered, orphan tasks/patches (E21-S4 queries).
- `E24-S4-T2`: drift dashboard — open drift findings by type/tier with file/spec locations (E22-S3), waiver review (E22-S4-T3).
- `E24-S4-T3`: evidence review surface — per-requirement evidence bundles (diffs, test results, eval scores, screenshots) rendered for human review (E22-S5).

| Criterion | Detail |
| --- | --- |
| Functional | A reviewer can answer "is R-12 satisfied, and on what evidence?" from one screen; drift findings link to both the spec and the code location; waivers are listed and auditable |
| Non-functional | Dashboards read-only against `/v2` (no side-band computation in the UI); p95 render < 1 s on cached queries |
| DoR (specific) | E21-S4, E22-S3/S5 APIs available |
| DoD (specific) | e2e review-flow test; a11y audit; docs |
| Dependencies | E21-S4, E22-S3, E22-S4, E22-S5, E17 |

### E24-S5 — Harness composer

Subtasks:
- `E24-S5-T1`: visual composer binding spec + flow + loop policy + gates + budgets into a `harness.yaml` (YAML round-trip like the E10-S3 flow editor).
- `E24-S5-T2`: run controls — start/pause/resume/fork harness runs; live iteration timeline with gate flips (E23-S5 stream).
- `E24-S5-T3`: race configuration — pick N candidates (agent/model/strategy) and review the winner decision.

| Criterion | Detail |
| --- | --- |
| Functional | A composed harness validates against `harness.schema.json` and round-trips visual↔YAML; the iteration timeline reflects `harness.*` events live; a race's winner rationale is visible |
| Non-functional | Composer reuses the E10-S3/E17-S6 flow-builder foundation (no second graph editor); WCAG 2.2 AA |
| DoR (specific) | E23-S1/S5 available; flow-builder component reviewed for reuse |
| DoD (specific) | Round-trip test; e2e compose→run test; a11y audit; docs |
| Dependencies | E23, E17-S6 |

## v1/v2 precursor / starting point

- The E17 Control Center gives this epic its shell, plans/patches interaction
  patterns, and the flow builder to extend — no screen here starts from a
  blank page. The plans screen (E17-S2) is the direct ancestor of the task
  board; the flow builder (E17-S6) is the base of the harness composer.
- Nothing spec-specific exists in the frontend today; all five stories are new
  screens/panels on existing foundations, consuming only E20–E23 APIs.

## Epic exit checklist

- [ ] All 5 stories meet the global DoD plus story-specific DoD above.
- [ ] Every screen consumes exclusively `/v2` (API-first contract test, §2.13).
- [ ] WCAG 2.2 AA verified on all new screens.
- [ ] `docs/v2_platform/progress.md` updated.
