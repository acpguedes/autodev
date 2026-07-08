# E10 — UI/UX & Design System

**Wave:** Beta
**Status:** Done (2026-07-08) · **Stories:** 4/4 complete
**Depends on:** E3, E9, E1
**Enables:** consumes API/streaming; hosts the flow editor and pluggable UI panels
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.4 (E10), §18.8, §18.9

## Objective

Deliver the **Web UI (Next.js)** with a **Design System** (shadcn/ui + Tailwind,
Design Tokens), key screens, a **visual flow editor**, catalogs, and dashboards, with
**WCAG 2.2 AA** accessibility.

## Key result

An operator creates/edits flows, triggers runs, follows streaming, and browses
agent/skill/plugin catalogs through an accessible UI, 100% keyboard-navigable.

## Stories

### E10-S1 — Design System and Design Tokens

Subtasks:
- `E10-S1-T1`: base component library (shadcn/ui + Tailwind) and token-based theming.
- `E10-S1-T2`: color/typography/spacing/radius/shadow tokens with light/dark mode.
- `E10-S1-T3`: Storybook/component catalog with accessibility tests.

| Item | Content |
| --- | --- |
| CF | Reusable, documented components; light/dark themes; versioned tokens |
| CNF | WCAG 2.2 AA contrast and focus; keyboard navigation; components with a11y tests |
| DoR | Brand/token guide approved; Next.js stack defined |
| DoD | Storybook published; a11y audit with no blocking violations; token docs |
| Dependencies | — |

### E10-S2 — Key screens (sessions, runs, catalogs, dashboards)

Subtasks:
- `E10-S2-T1`: session/run screens with streaming and traces.
- `E10-S2-T2`: agent/skill/plugin catalogs with search and detail views.
- `E10-S2-T3`: cost/token/quota dashboards per tenant.

| Item | Content |
| --- | --- |
| CF | Operator sees runs live, inspects steps/traces, browses catalogs, and sees metrics |
| CNF | Acceptable perceived loading p95; AA accessibility; streaming consumption < 1 s |
| DoR | E9 (API/streaming) and E10-S1 ready |
| DoD | User flows tested (e2e); a11y validated; screen docs |
| Dependencies | E9, E10-S1 |

### E10-S3 — Visual flow editor

Subtasks:
- `E10-S3-T1`: graph canvas (nodes, conditional edges, sub-flows, map/reduce).
- `E10-S3-T2`: declarative editing synced with `flow.yaml` (round-trip).
- `E10-S3-T3`: real-time validation and human-in-the-loop in the UI.

| Item | Content |
| --- | --- |
| CF | Creates/edits a flow visually; exports/imports `flow.yaml` without loss; validates the graph and human nodes |
| CNF | Editor accessible by keyboard; deterministic round-trip; immediate validation feedback |
| DoR | E3 (Orchestration Engine) with a stable flow schema; E10-S1 ready |
| DoD | Round-trip tested; a11y AA on the canvas; editor docs |
| Dependencies | E3, E10-S1 |

### E10-S4 — Pluggable panels (UI Extension Points)

Subtasks:
- `E10-S4-T1`: UI extension point for panels contributed by plugins.
- `E10-S4-T2`: sandbox/permissions for plugin panels.
- `E10-S4-T3`: panel registration/discovery via the Plugin Host.

| Item | Content |
| --- | --- |
| CF | Plugins register UI panels; the user enables/disables them; panels honor tokens/theme |
| CNF | Panel isolation; inherited a11y; a panel failing does not break the app |
| DoR | E1 (Plugin Host) and E10-S1 ready; UI Extension contract approved |
| DoD | Example panel published; contract test; docs |
| Dependencies | E1, E10-S1 |

## v1 precursor / starting point

- The Next.js 14 App Router UI already exists with 6 pages (`/`, `/config`, `/agents`,
  `/plans`, `/skills`, `/patches`), but styling is pure CSS
  (`frontend/styles/globals.css`, ~695 lines), dark-theme only, with no component
  library — see `docs/feature_matrix.md` § Frontend. A Tailwind + shadcn/ui rebuild is
  already planned as Units 11-19 in `docs/implementation/mvp_refactor_plan.md`, which
  maps closely onto E10-S1/E10-S2 (design tokens, app shell, dashboard, diff viewer,
  plan approval UI, run history, observability dashboard).
- There is no visual flow editor and no plugin-panel extension point today; E10-S3 and
  E10-S4 start from zero and explicitly depend on E3's stable `flow.yaml` schema and
  E1's Plugin Host, respectively.

## Epic exit checklist

- [ ] All 4 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [ ] Contract tests green for the UI Extension Point; a11y audit passes with no
      blocking WCAG 2.2 AA violations.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] Beta wave entry item "Design System, key screens, visual flow editor, pluggable
      panels" satisfied (§18.9).
