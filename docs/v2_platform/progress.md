# v2 Platform — Implementation Progress

> Living tracker for the v2.0 platform refactor described in
> `docs/architecture/v2_platform_reference.md`. Update this file whenever a story or
> epic changes state, whenever a wave gate is cleared, and whenever an ADR/RFC is
> added (cross-check `docs/v2_platform/decisions/README.md`). This file is the single
> place to look to answer "where are we on the v2 rewrite?" without re-reading the
> 6600-line reference document.

**Last updated:** 2026-07-02 (`v1.0.0` baseline tagged; no epic work started yet)

## How to update this file

1. When a story (`E<n>-S<m>`) moves through the workflow states in §18.1 of the
   reference doc (Backlog -> Ready -> In Progress -> In Review -> Validation -> Done),
   update the "Stories complete" count and "Status" for its epic in the table below.
2. When an epic's last story reaches Done, flip its "Status" to `Done` and record the
   date in the Changelog.
3. When a wave's exit criteria (§18.9, reproduced below) are fully satisfied, flip the
   wave's status and record the date.
4. Keep this file and each `phases/E<n>_*.md` "Status" header in sync — the phase doc
   is the detail, this file is the summary.
5. Do not mark anything "Done" without the evidence the global DoD
   (`templates/dod_checklist.md`) requires (green contract tests, docs updated,
   observability verified, etc.).

## Current wave: Alpha (in progress)

No epic in this framework has been started yet. The repository already contains
several **informal precursors** to Alpha-wave capabilities (auto-discovered plugin
seams, an agent/skill registry, dynamic orchestration behind a flag, a SQLite store
abstraction with migrations) — see `docs/feature_matrix.md` for their exact status and
each `phases/E<n>_*.md` file's "v1 precursor / starting point" section for how they
map onto the v2 epics. None of them satisfy the v2 contracts (manifests, `hostApi`
versioning, permissions, contract tests) as written, so they are starting points, not
completed epic work.

The v1 codebase is now frozen at the `v1.0.0` git tag (see `CHANGELOG.md`) as the
baseline these epics build on and are measured against — `make check` (lint, mypy,
backend/frontend tests, frontend build) is green and `docs/feature_matrix.md` is
current as of that tag. **Next action: pick up `E0-S3` (PostgreSQL state store)** —
read `phases/e0_foundations_hardening.md` and
`agent_guide.md` §1-2 before starting.

## Epic status

| Epic | Name | Wave | Status | Stories | Depends on | Doc |
| --- | --- | --- | --- | --- | --- | --- |
| E0 | Foundations & Hardening | Alpha | In progress | 3/7 | — | [phases/e0_foundations_hardening.md](phases/e0_foundations_hardening.md) |
| E1 | Plugin Core & SDK | Alpha | Not started | 0/5 | E0 | [phases/e1_plugin_core_sdk.md](phases/e1_plugin_core_sdk.md) |
| E2 | Agent Framework | Alpha | Not started | 0/5 | E0, E1 | [phases/e2_agent_framework.md](phases/e2_agent_framework.md) |
| E3 | Orchestration Engine | Alpha/Beta | Not started | 0/6 | E0, E2 | [phases/e3_orchestration_engine.md](phases/e3_orchestration_engine.md) |
| E4 | Reasoning | Beta | Not started | 0/4 | E1, E2 | [phases/e4_reasoning.md](phases/e4_reasoning.md) |
| E5 | Routing / Selection / Evaluation | Beta | Not started | 0/4 | E2, E4 | [phases/e5_routing_selection_evaluation.md](phases/e5_routing_selection_evaluation.md) |
| E6 | Skills v2 | Beta | Not started | 0/5 | E1 | [phases/e6_skills_v2.md](phases/e6_skills_v2.md) |
| E7 | Context & RAG | Beta | Not started | 0/4 | E1, E2, E8, E5 | [phases/e7_context_rag.md](phases/e7_context_rag.md) |
| E8 | Persistence & Data | Alpha/Beta | Not started | 0/4 | E0 | [phases/e8_persistence_data.md](phases/e8_persistence_data.md) |
| E9 | APIs, Events & MCP | Alpha/Beta | Not started | 0/4 | E8, E2, E6 | [phases/e9_apis_events_mcp.md](phases/e9_apis_events_mcp.md) |
| E10 | UI/UX & Design System | Beta | Not started | 0/4 | E3, E9, E1 | [phases/e10_ui_ux_design_system.md](phases/e10_ui_ux_design_system.md) |
| E11 | Observability, Security & Multi-tenant | Beta | Not started | 0/4 | E0, E8, E9-S1, E4 | [phases/e11_observability_security_multitenant.md](phases/e11_observability_security_multitenant.md) |
| E12 | Quality & Evals | Alpha/Beta | Not started | 0/4 | E0, E1-E6, E5 | [phases/e12_quality_evals.md](phases/e12_quality_evals.md) |
| E13 | Marketplace & GA | GA | Not started | 0/4 | E1, E12-S2, E11-S4, E0-E12 | [phases/e13_marketplace_ga.md](phases/e13_marketplace_ga.md) |

Total: **3/64 stories complete** across 14 epics.

## Wave exit gates (§18.9 of the reference doc)

### v2.0-alpha — "usable extensible core"

Goal: prove the small core + pluggable edges end to end in local-first mode.
Anchor epics: **E0** (complete), **E1**, **E2**, **E3** (graph/checkpointing/
human-in-the-loop stories; visual editor can stay minimal), **E8-S1/E8-S2**,
**E9-S1** (minimal API), **E12-S1** and the start of **E12-S2**.

- [ ] A declarative flow executes an agent-plugin end to end with durable state and
      event-store replay.
- [ ] Contract tests green for the E1/E2/E3 extension points.
- [ ] Local-first mode (SQLite + stub provider) runs with no external dependencies.
- [ ] Core coverage >= 85%.
- [ ] Basic per-step traces emitted.

### v2.0-beta — "full platform in controlled production"

Goal: complete intelligence, context, data, API, UI, security, and quality
capabilities for real, controlled operation. Anchor epics: **E4**, **E5**, **E6**,
**E7**, **E8-S3/E8-S4**, **E9-S2/S3/S4**, **E10**, **E11**, **E12-S2/S3/S4**.

- [ ] The real plan -> code -> apply patch -> validate in sandbox -> evaluate flow runs
      with RBAC, fail-closed budgets, and end-to-end traces.
- [ ] Hybrid retrieval reaches p95 < 300 ms and the recall baseline.
- [ ] Run streaming starts < 1 s.
- [ ] Every extension point has a green contract test and quality gates block merges.
- [ ] UI is WCAG 2.2 AA on key screens; flow editor round-trips.
- [ ] Backup/restore validated (RPO <= 5 min, RTO <= 30 min) in staging.

### v2.0-GA — "general availability"

Goal: open the Marketplace and declare general availability with SLO, security, and
upgrade-support guarantees. Anchor epic: **E13** complete, plus final hardening, the
v1 upgrade migration, and release notes.

- [ ] Verified plugin publish/install (signature + SBOM) end to end.
- [ ] Control Plane SLO 99.9% and read p95 < 300 ms under load
      (>= 100 concurrent runs per reference node).
- [ ] RPO <= 5 min / RTO <= 30 min proven in production.
- [ ] GA checklist signed off (SLOs, security, docs, backups, evals).
- [ ] v1 -> v2 upgrade path documented and tested.
- [ ] GA release published with notes.
- [ ] `docs/v2_platform/documentation_rebuild.md` executed for the GA milestone.

## Changelog

Add a dated entry every time a story/epic/wave status changes.

- **2026-07-02** — Created `docs/v2_platform/` (this tracker, per-epic phase docs,
  process/manifest templates, agent guide, decisions log, documentation-rebuild
  playbook). No implementation work started. Baseline captured from
  `docs/architecture/v2_platform_reference.md` and `docs/feature_matrix.md`.
- **2026-07-02** — Packaged and tagged the v1 architecture as `v1.0.0` (see
  `CHANGELOG.md`) immediately before starting Alpha-wave work: validated `make check`
  end-to-end, fixed two mypy failures uncovered by that pass, refreshed
  `docs/feature_matrix.md` (several rows had gone stale — typed settings module,
  `GET /features`, env-driven CORS, CI coverage/smoke gates, the Tailwind/shadcn
  foundation — plus a new Security section and reclassifying tree-sitter extraction
  as a `stub`), and synced the status banner in
  `docs/architecture/weaknesses_and_strategies.md`. No epic/story status changes from
  this pass — it is a baseline/documentation checkpoint, not epic work.
- **2026-07-03** — Completed E0-S0: added the containerized backend dev/test runtime,
  Compose wiring for container CLI/test execution, and README/v2 guidance making the
  backend container the baseline E0 execution environment.
- **2026-07-03** — Completed E0-S1: added Makefile container targets for backend
  build/up/shell/test/check/down/logs and documented the container-first workflow in
  `docs/testing.md`.
- **2026-07-03** — Completed E0-S2: added typed declarative settings with
  local/prod profiles, JSON file plus environment precedence, fail-fast
  `autodev config validate`, redacted settings inspection, and `docs/config.md`.
