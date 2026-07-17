# v2 Platform — Implementation Progress

> Living tracker for the v2.0 platform refactor described in
> `docs/architecture/v2_platform_reference.md`. Update this file whenever a story or
> epic changes state, whenever a wave gate is cleared, and whenever an ADR/RFC is
> added (cross-check `docs/v2_platform/decisions/README.md`). This file is the single
> place to look to answer "where are we on the v2 rewrite?" without re-reading the
> 6600-line reference document.

**Last updated:** 2026-07-17 (**Beta hardening wave planned — epics E32–E35
added**: isolated-execution Beta slice, secrets & credential governance,
packaging/global install, and Beta readiness gates — 13 new stories; see
`phases/e32_isolated_execution_beta.md` … `phases/e35_beta_readiness_gates.md`,
ADR-013/014/015 (all *Proposed*, decisions pending) and
`beta_gap_analysis.md`. Previous entry: **E8 complete — 4/4**: **E8-S3 — Artifact
Store** merged in PR #85 (pointer store `backend/artifacts/pointers.py` with
MinIO/local backends, presigned URLs behind
`autodev_artifact_retention_days`, referenced-object GC in
`backend/artifacts/cleanup.py`, CLI + config surface, closing the earlier T2
gap) and **E8-S4 — Backup, RPO/RTO & restore runbook** merged in PR #84
(backup/restore tooling over the persistence adapters, tenancy-migration and
artifact-store test coverage, RPO/RTO targets + restore runbook documented in
`phases/e8_persistence_data.md`). Known follow-up: split the oversized
`backend/persistence/sqlite_adapter.py`. Previous entry: **E8-S2 — Event
Store and run durability complete** on `epic/e8-persistence-data`: durable append-only `events` table
for canonical envelopes ordered per partition (`backend/events/store.py` +
`backend/events/records.py`), transactional `event_projections`
materialization for O(1) status queries, `reconstruct_run()` rebuilding a run
purely from stored events (verified with a deterministic-replay DoD test),
retention-based compaction via `autodev_event_retention_days`, and Event Bus
wiring behind `autodev_event_store_enabled` (default on). E8 is now 2/4.
Previous entry: **Planning-only: added the "v2.2 — Concept
Integration" wave — epics E26–E31** (July 2026 SOTA evaluation of mainstream AI
dev + creative platforms and 2024–2026 literature, integrated as: Runtime Context
Engineering, Execution-Grounded Verification & Test-Time Compute, Execution
Environments & Self-Verification, Durable Learning & Skill Library, FinOps &
Autonomy Governance, Library Spec Registry), specified in reference §23 +
§18.7.18–§18.7.23 + §18.9, proposed in **RFC-008** (Draft), with phase docs
`phases/e26_*.md`–`phases/e31_*.md`. No implementation. Previous entry:
**Planning-only: added the "v2.1 — Spec & Harness"
wave — epics E20–E25** (spec-driven development + agent-harness layer: Spec Core,
Spec Compiler, Spec Verification, Harness Engine, Spec Studio, Extension Studio),
specified in reference §22 + §18.7.12–§18.7.17 + §18.9, proposed in **RFC-007**
(Draft), with phase docs `phases/e20_*.md`–`phases/e25_*.md`. No implementation.
E19 remains reserved for the proposed visual-parity audit. Previous entry:
**E18 — Control Center Front Door & Run Experience epic
complete (5/5)** on `epic/e18-front-door`: **S1** `GET /` service descriptor
(JSON for API clients, CSP-clean HTML pointer page for browsers, `AUTODEV_UI_URL`
setting, `/` public like `/health`); **S2** self-hosted Swagger UI `/docs` (vendored
`swagger-ui-dist` 5.32.8, zero inline script/CDN, works offline, CSP untouched);
**S3** single-command run (`make run` via `scripts/run_dev.sh`, compose `full`
profile + `make container-up-full`, `check-compose` gate, README quickstart now leads
with the UI); **S4** shell chrome i18n (`shell.*` namespace en + pt-BR, navModel
`labelKey`, key-parity test, shell components under the eslint i18n `error` gate);
**S5** docs hygiene (README troubleshooting entry, `frontend/chat-ui/` placeholder
removed, this tracker updated). The visual-parity audit remains deferred as proposed
**E19**. Previous entry: **E17 — Frontend Redesign: Control Center Screens epic
complete (6/6)** on `epic/e17-control-center-screens`, merged to `main` via PR #78 —
all seven prototype views (chat execution, plans with approval gates, patches review,
sessions, config, extensions hub, flow builder) now live on the E15 shell against the
E16 `/v2` endpoints; one known fast-follow recorded in the phase doc (S1↔S4
reopen-session-as-chat query-param consumption).
Previous entry: **E16 — Frontend Redesign: Control-Plane API Enablement
epic complete (4/4)** on `epic/e16-redesign-api-enablement`, merged to `main`. Backend-only:
four additive `/v2` surfaces the E17 Control Center screens will consume — **E16-S1**
chat/turn endpoints + `run.timeline.*` events + agent-role→step mapping; **E16-S2**
per-step plan approval state machine (`draft→under_review→approved|rejected→executing→completed`)
+ `plan.step.*` events; **E16-S3** patch review/apply (changed-files, per-file diff,
edited-content override, dry-run-default apply/discard reusing the E0 patch engine) +
`patch.*` events; **E16-S4** unified extensions catalog (agents/skills/plugins/MCP) with
delegated enable/disable + agent create/edit + live provider config/status. Routers
auto-discovered; event catalog grew append-only 20 → 31 types; contract tests green per
story. Previous entry: **E15 — Frontend Redesign: Design Language & App Shell
epic complete (4/4)** on `epic/e15-design-language-shell`, merged to `main`. **E15-S1**:
additive `--ds-*` warm-paper/charcoal token layer, redesign typefaces,
`--ds-token-version` 2.0.0. **E15-S2**: three-region app shell (250px rail / 64px
contextual header / dismissible 400px execution panel) wrapping every `frontend/app/`
route, with persisted panel/nav state, Playwright e2e navigation suite
(`frontend/e2e/`), and axe-covered shell Storybook stories. **E15-S3**: purged legacy
`styles/globals.css` classes from the 6 remaining pages in favor of the token-driven
`components/ui` kit, plus a router-mock and WCAG contrast fix in the shell Storybook
stories. **E15-S4**: dependency-free i18n foundation (`frontend/lib/i18n/`) with
English default + pt-BR, externalized copy in `app/page.tsx` and
`ExecutionConsolePanel.tsx`, a `SidebarRail` locale switcher, and an
`eslint-plugin-i18next` lint gate. Gates: lint 0 errors, `tsc --noEmit` clean, 22/22
test files (89/89 tests), 12/12 e2e tests. E10 — UI/UX & Design System epic (4/4) on
`epic/e10-ui-ux-design-system` remains complete from the prior entry.)

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

The first three Alpha epics are complete. **E0** delivered the foundations
(containerized backend runtime, typed declarative settings, PostgreSQL state
store, OpenTelemetry traces + Prometheus counters, the security baseline, and
Redis queue/cache/locks + local/MinIO artifact stores). **E1** delivered the
Plugin Core & SDK (`plugin.yaml` manifests + published schema, Plugin Host
discovery/lifecycle, default-deny permissions with brokered Host API access,
the Python SDK with scaffold CLI and contract-test harness, and the
active-plugin registry behind `/v2/plugins/active`). **E2** delivered the Agent
Framework (`agent.yaml` manifests, the durable Agent Registry with SemVer
resolution and `/v2/agents/catalog`, the Agent Runtime with fail-closed
budgets and output guardrails, permissioned tool/skill mediation with the
provider abstraction, and `autodev/agent-coder` packaged as a reference agent
plugin).

The v1 codebase remains frozen at the `v1` git tag (see `CHANGELOG.md`) as
the baseline these epics build on and are measured against. The remaining
**informal v1 precursors** (dynamic orchestration behind a flag for E3, the
SQLite store abstraction for E8, the v1 skills registry for E6) are starting
points only — they do not satisfy the v2 contracts. E3's Alpha slice (S1-S5) is
complete and verified (flow suite 38/38 green); its last story, **E3-S6**
(visual flow editor), is now **complete** — delivered via **E10-S3**
(deterministic `flow.yaml`↔manifest round-trip, `frontend/lib/flow/yaml.ts`) and
**E17-S6** (canvas/palette/inspector, inline validation, keyboard + storybook-axe
a11y, `frontend/e2e/flow-builder.spec.ts`). Remaining Alpha anchor work: **E12-S1** (E8 and E9 are now
complete). The frontend redesign epics **E15** (done) → **E16** → **E17** (Execution Control Center prototype)
are planned to run before the E11 kickoff; **E15**, **E16**, and **E17** are now
complete — the redesigned Control Center is implemented end to end. **E18** (Control
Center Front Door & Run Experience, also complete) made that UI the platform's front
door: root service descriptor, self-hosted `/docs` under the strict CSP, and
single-command `make run`. A visual-parity audit of the screens against the prototype
(fonts, tokens, spacing, per-screen interaction details, per-screen checklist derived
from ADR-012 and the prototype `shots/`) remains deferred as a proposed **E19**.
**Next action: E12-S1; follow `agent_guide.md` §1-4 quality
rules (mandatory from E3 onward).**

## Epic status

| Epic | Name | Wave | Status | Stories | Depends on | Doc |
| --- | --- | --- | --- | --- | --- | --- |
| E0 | Foundations & Hardening | Alpha | Done | 7/7 | — | [phases/e0_foundations_hardening.md](phases/e0_foundations_hardening.md) |
| E1 | Plugin Core & SDK | Alpha | Done | 5/5 | E0 | [phases/e1_plugin_core_sdk.md](phases/e1_plugin_core_sdk.md) |
| E2 | Agent Framework | Alpha | Done | 5/5 | E0, E1 | [phases/e2_agent_framework.md](phases/e2_agent_framework.md) |
| E3 | Orchestration Engine | Alpha/Beta | Done | 6/6 | E0, E2 | [phases/e3_orchestration_engine.md](phases/e3_orchestration_engine.md) |
| E4 | Reasoning | Beta | Done | 4/4 | E1, E2 | [phases/e4_reasoning.md](phases/e4_reasoning.md) |
| E5 | Routing / Selection / Evaluation | Beta | Done | 4/4 | E2, E4 | [phases/e5_routing_selection_evaluation.md](phases/e5_routing_selection_evaluation.md) |
| E6 | Skills v2 | Beta | Done | 5/5 | E1 | [phases/e6_skills_v2.md](phases/e6_skills_v2.md) |
| E7 | Context & RAG | Beta | Done | 4/4 | E1, E2, E8, E5 | [phases/e7_context_rag.md](phases/e7_context_rag.md) |
| E8 | Persistence & Data | Alpha/Beta | Done | 4/4 | E0 | [phases/e8_persistence_data.md](phases/e8_persistence_data.md) |
| E9 | APIs, Events & MCP | Alpha/Beta | Done | 4/4 | E8, E2, E6 | [phases/e9_apis_events_mcp.md](phases/e9_apis_events_mcp.md) |
| E10 | UI/UX & Design System | Beta | Done | 4/4 | E3, E9, E1 | [phases/e10_ui_ux_design_system.md](phases/e10_ui_ux_design_system.md) |
| E11 | Observability, Security & Multi-tenant | Beta | Not started | 0/4 | E0, E8, E9-S1, E4 | [phases/e11_observability_security_multitenant.md](phases/e11_observability_security_multitenant.md) |
| E12 | Quality & Evals | Alpha/Beta | Not started | 0/4 | E0, E1-E6, E5 | [phases/e12_quality_evals.md](phases/e12_quality_evals.md) |
| E13 | Marketplace & GA | GA | Not started | 0/4 | E1, E12-S2, E11-S4, E0-E12 | [phases/e13_marketplace_ga.md](phases/e13_marketplace_ga.md) |
| E14 | Real Task Execution & Governed Autonomy | Beta | Not started | 0/7 | E2, E3, E9-S1, E11-S4 | [phases/e14_real_execution_governance.md](phases/e14_real_execution_governance.md) |
| E15 | Frontend Redesign: Design Language & App Shell | Beta | Done | 4/4 | E10 | [phases/e15_design_language_shell.md](phases/e15_design_language_shell.md) |
| E16 | Frontend Redesign: Control-Plane API Enablement | Beta | Done | 4/4 | E9, E3, E8-S1 | [phases/e16_redesign_api_enablement.md](phases/e16_redesign_api_enablement.md) |
| E17 | Frontend Redesign: Control Center Screens | Beta | Done | 6/6 | E15, E16 | [phases/e17_control_center_screens.md](phases/e17_control_center_screens.md) |
| E18 | Control Center Front Door & Run Experience | Beta | Done | 5/5 | E15, E16, E17 | [phases/e18_front_door_run_experience.md](phases/e18_front_door_run_experience.md) |
| E20 | Spec Core: Constitution, Spec Artifacts & Registry | v2.1 | Not started | 0/5 | E1, E8-S1, E9, E16-S2 (pattern) | [phases/e20_spec_core.md](phases/e20_spec_core.md) |
| E21 | Spec Compiler: Scoping, Decomposition & Traceability | v2.1 | Not started | 0/4 | E20, E3, E5, E7 | [phases/e21_spec_compiler.md](phases/e21_spec_compiler.md) |
| E22 | Spec Verification: Executable Acceptance & Drift Enforcement | v2.1 | Not started | 0/5 | E20, E21, E12, E14-S1–S4, E7-S1 | [phases/e22_spec_verification.md](phases/e22_spec_verification.md) |
| E23 | Harness Engine & Loop Engineering | v2.1 | Not started | 0/5 | E3, E4, E14, E20, E22 | [phases/e23_harness_engine.md](phases/e23_harness_engine.md) |
| E24 | Spec Studio: AI-Assisted Spec Builder (UI) | v2.1 | Not started | 0/5 | E15–E17, E20–E23 | [phases/e24_spec_studio.md](phases/e24_spec_studio.md) |
| E25 | Extension Studio: AI-Assisted Agent/Skill/Plugin Development | v2.1 | Not started | 0/4 | E1, E6, E12-S2, E20, E23; E13 (publish) | [phases/e25_extension_studio.md](phases/e25_extension_studio.md) |
| E26 | Agent Runtime Context Engineering | v2.2 | Not started | 0/4 | E2, E3, E8; E23-S2 (options) | [phases/e26_runtime_context_engineering.md](phases/e26_runtime_context_engineering.md) |
| E27 | Execution-Grounded Verification & Test-Time Compute | v2.2 | Not started | 0/5 | E5, E22, E23, E14, E12 | [phases/e27_execution_grounded_verification.md](phases/e27_execution_grounded_verification.md) |
| E28 | Execution Environments & Self-Verification | v2.2 | Not started | 0/4 | E14, E0-S7, E9-S4, E22-S5 | [phases/e28_execution_environments.md](phases/e28_execution_environments.md) |
| E29 | Durable Learning & Skill Library | v2.2 | Not started | 0/4 | E6, E7, E8, E22 | [phases/e29_learning_skill_library.md](phases/e29_learning_skill_library.md) |
| E30 | FinOps & Autonomy Governance | v2.2 | Not started | 0/4 | E2, E3 (ADR-006), E5, E11 | [phases/e30_finops_governance.md](phases/e30_finops_governance.md) |
| E31 | Library Spec Registry | v2.2 | Not started | 0/4 | E20, E7, E14; E13 (publish) | [phases/e31_library_spec_registry.md](phases/e31_library_spec_registry.md) |
| E32 | Isolated Execution Environment (Beta slice) | Beta | Not started | 0/4 | E14, E11-S4; E28 (contracts) | [phases/e32_isolated_execution_beta.md](phases/e32_isolated_execution_beta.md) |
| E33 | Secrets & Credential Governance | Beta | Not started | 0/3 | E32, E0-S5, E11-S4 | [phases/e33_secrets_credential_governance.md](phases/e33_secrets_credential_governance.md) |
| E34 | Packaging & Global Install | Beta | Not started | 0/3 | E14-S7 (CLI), E32 | [phases/e34_packaging_global_install.md](phases/e34_packaging_global_install.md) |
| E35 | Beta Readiness Gates & Evidence | Beta | Not started | 0/3 | E32-E34, E11, E12 | [phases/e35_beta_readiness_gates.md](phases/e35_beta_readiness_gates.md) |

Total: **71/156 stories complete** across 35 epics (E19 is a proposed
visual-parity audit, reserved but not yet planned — see the E18 phase doc).
*(2026-07-17: total recomputed from the per-epic Done column — the previous
"51" predated E15–E18 completion and had drifted; +13 planned stories from
the new E32–E35 Beta-hardening epics.)*

\* **E8-S1 is now complete (2026-07-06)**: on top of the scoped tenancy/
reversible-migration slice landed as an E7 prerequisite (ADR-010:
`decisions/ADR-010-e8s1-scoped-tenancy.md`), the remaining T3/T4 work
landed — mandatory `tenant_id` scoping threaded through every
`SessionRepository`/`RunRepository`/`MessageRepository`/`PlanRepository`/
`EvalResultRepository`/`ScoreSnapshotRepository` method on both
`SQLiteStore`/`SQLitePlanStore` and `PostgresStore`/`PostgresPlanStore`
(the latter via `set_postgres_tenant()` + RLS), a new `tenant_id` migration
for `plan_documents`/`plan_approvals`, negative-case tenant-isolation tests,
and caller-site threading in the two modules that called Protocol methods
directly (`backend/orchestrator/service.py`,
`backend/context/providers/session_memory.py`). `run_steps`,
`plugin_events`, and `score_snapshot_promotions` intentionally keep no
`tenant_id` column of their own — they are scoped transitively via `JOIN`
to their parent row's tenant (documented at
`backend/persistence/migrations/versions.py` lines 14-17); this was
previously miscategorized in this doc as "not done" but is by design, not a
gap. **E8-S3 (Artifact Store) is complete**: T3 (per-tenant pre-signed URLs)
and T4 (orphan cleanup) landed in `backend/artifacts/store.py` +
`backend/artifacts/cleanup.py`, and T2 (persisting `ArtifactPointer`
metadata in the State Store) landed in `backend/artifacts/pointers.py`
(`ArtifactPointerStore`, PR #85), so cleanup is now reference-based GC over
the durable pointer registry rather than an age heuristic. **E8-S2 (Event Store)
is complete (2026-07-16)** — see the changelog entry below; **E8-S4
(Backup/RPO/RTO) is complete (PR #84)**. Known follow-up: `backend/persistence/postgres_adapter.py`
is now 713 lines, over this repo's 500-line-per-file guideline — a split
into `PostgresStore`/`PostgresPlanStore` modules is reasonable future
cleanup, out of scope for this pass.

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
**E7**, **E8-S3/E8-S4**, **E9-S2/S3/S4**, **E10**, **E11**, **E12-S2/S3/S4**,
**E14** (real task execution, permission/approval policy, governed sandbox
runners, Web UX + interactive shell for approval, `autodev` CLI install).

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

- **2026-07-17** — **Tracker reconciliation (docs-only, no code change)** —
  cross-checked the tracker against the codebase and closed two stale gaps that
  were already implemented: (1) **E8-S3 T2** (durable `ArtifactPointer` metadata
  in the State Store) is implemented in `backend/artifacts/pointers.py`
  (`ArtifactPointerStore`, PR #85) — the E8-S1/S3 footnote wrongly still called
  T2 "not implemented" and E8-S4 "not started"; both are corrected. (2)
  **E3-S6** (visual flow editor) is delivered via **E10-S3** (`flow.yaml`↔manifest
  round-trip, `frontend/lib/flow/yaml.ts` + `yaml.test.ts`) and **E17-S6**
  (`FlowCanvas`/`FlowPalette`/`NodeInspector`, `frontend/lib/flow/validate.ts`,
  keyboard + storybook-axe a11y, `frontend/e2e/flow-builder.spec.ts`), meeting
  its render/round-trip/inline-validation/a11y DoD. E3 moves to **6/6 Done**;
  epic total **70 → 71**. No source files changed.
- **2026-07-16** — **E8-S2 — Event Store and run durability complete** on
  `epic/e8-persistence-data` (story branch `story/e8-s2-event-store`).
  **T1**: append-only `events` table persisting every canonical
  `EventEnvelope` published on the Event Bus (catalog `domain.entity.action`
  types), gap-free per-partition `sequence` (`UNIQUE (partition_key,
  sequence)`), `tenant_id` column, SQLite + Postgres DDL
  (`backend/events/store.py`; record types/DDL/decoders in
  `backend/events/records.py`). Wired as a wildcard bus subscriber in
  `get_event_bus()` behind the new `autodev_event_store_enabled` setting
  (default on); a per-thread cached write connection keeps the append
  ~0.03 ms so the checkpoint-overhead NFR test still passes (fast-append
  CNF). **T2**: `EventStore.reconstruct_run()` rebuilds a run view (status,
  step trail, terminal outcome) purely from stored events; DoD test runs a
  real `FlowEngine` flow, checks the reconstruction against the
  `FlowRunStore` record, and asserts `FlowEngine.replay_run()` is
  deterministic. **T3**: `event_projections` materialization (derived
  status, last sequence/type/time, per-type counts) updated in the same
  transaction as each append; `get_projection()`/`list_projections()` give
  O(1) status queries. **T4**: `EventStore.purge_expired()` compacts events
  of terminal partitions older than `autodev_event_retention_days`
  (default 30, `-1` = keep forever), preserving the projection row as the
  compacted summary. Tests: `backend/tests/test_event_store.py` (13 cases:
  ordering/resume/round-trip, projections, reconstruction+replay, bus
  wiring on/off, retention). Docs: `docs/config.md` env inventory
  (including the previously undocumented `AUTODEV_EVENT_BUS`),
  `docs/feature_matrix.md` § Persistence, E8 phase doc. Full backend suite
  green before the story→epic merge.

- **2026-07-13** — Planning-only, no implementation: added the **"v2.2 — Concept
  Integration" wave — epics E26–E31**, closing the July 2026 state-of-the-art
  evaluation (11 mainstream agentic dev platforms — Claude Code/Agent SDK, Cursor,
  OpenAI Codex, Devin, Manus, GitHub Copilot, Google Antigravity/Jules, Windsurf,
  OpenHands/Aider/Cline, Factory/Amp/Warp/Replit-class, Spec Kit/Kiro/Tessl; 7
  creative platforms evaluated for transferable concepts — ElevenLabs, HeyGen,
  Runway/Pika/Kling, Google Flow/Veo, Suno/Udio, Midjourney; ~50 papers
  2024–2026). Every evaluated concept is dispositioned in RFC-008 (covered /
  gap / guidance / rejected); the gaps become: **E26 — Agent Runtime Context
  Engineering** (KV-cache-aware invariants + hit-rate metric, `condenser`
  extension point, tool masking over removal, external memory with reversible
  compression + recitation + keep-errors-in-context); **E27 — Execution-Grounded
  Verification & Test-Time Compute** (best-of-N candidate sets with
  execution-based selection, multi-verifier composition + calibrated LLM judges,
  cross-model "oracle" second opinion via `distinct_provider_from`,
  property-based acceptance oracles, weak-oracle/reward-hacking hardening +
  internal eval methodology); **E28 — Execution Environments &
  Self-Verification** (machine snapshots in MinIO with `/v2/snapshots`, tiered
  isolation with a microVM class for untrusted code, browser self-verification
  runner feeding evidence bundles, code-mode MCP); **E29 — Durable Learning &
  Skill Library** (verified embedding-indexed playbook/skill/insight library at
  `/v2/knowledge`, ACE-style bounded-delta curation, progressive-disclosure
  skill packs with SKILL.md interop, machine-generated repo knowledge); **E30 —
  FinOps & Autonomy Governance** (`cost_estimator` kind + `/v2/estimates`
  pre-run price legibility, hierarchical fail-closed budget caps + checkpoint
  ceilings + kill switches, draft-vs-final tiers via Selector `tier` policy,
  per-surface metering feeding E11 dashboards); **E31 — Library Spec Registry**
  (Tessl-style verified dependency specs at `/v2/library-specs`,
  sandbox-verified claim acquisition, anti-hallucination retrieval provider,
  marketplace sharing with provenance — resolves RFC-007's deferred open
  question). Guidance adopted without epics: multi-agent restraint (MAST),
  benchmark discipline (disclose-the-harness, decontaminated held-out internal
  evals), provenance-by-design/default-private sharing, KV-cache economics
  awareness. Deliverables of this pass: **RFC-008** (Draft — platform evaluation
  matrix, 45-row concept disposition catalog, contract-surface overview,
  rejected alternatives incl. swarm-by-default and fine-tuning-based learning,
  research annex), reference-doc extensions (new **§23** narrative, roadmap
  entries **§18.7.18–§18.7.23**, new **v2.2 wave** in §18.9), six phase docs
  (`phases/e26_runtime_context_engineering.md` …
  `phases/e31_library_spec_registry.md`, 25 stories total), decisions index row,
  and this tracker (story total now 50/143 across 31 epics). Sequencing note:
  E26/E30 can start on stable E2/E3; E27/E28 gate on E14+E12; the v2.2 critical
  path still runs through finishing E14, E12, and E11.
- **2026-07-12** — Planning-only, no implementation: added the **"v2.1 — Spec &
  Harness" wave — epics E20–E25** — the spec-driven-development + agent-harness
  layer positioning the platform against Cursor/Claude Code/Codex/Antigravity
  (integrated specs + harness, which none of them ship together). **E20 — Spec
  Core** (constitution + `spec.yaml` with EARS requirements, tenant-scoped Spec
  Registry with immutable published versions, OpenSpec-style requirement-scoped
  change deltas, `/v2/specs`, "Spine" spec Context Provider); **E21 — Spec
  Compiler** (intake/scoping with pre-spec prototype stage, requirements→design→
  task dependency graph in waves, task-to-flow compilation reusing the Flow
  Engine, requirement↔task↔run↔patch↔test↔eval traceability graph); **E22 —
  Spec Verification** (acceptance criteria compiled to sandbox tests,
  requirement-targeted evals, Intent-vs-Evidence-graph drift detection as a
  blocking validation gate, same-change spec+code coupling with HARD/SOFT/AUTO
  tiers, human-legible evidence bundles); **E23 — Harness Engine**
  (`harness.yaml` binding spec+flow+loop policy+gates+budgets with typed result
  states, pluggable loop policies (evaluator-optimizer / fresh-context /
  circuit-breaker / heartbeat), durable loop state with resume/fork, worktree
  isolation + task claiming + candidate race, `/v2/harnesses`); **E24 — Spec
  Studio** (constitution wizard, EARS-assisted spec editor with clarify loop,
  task board, drift/evidence dashboards, harness composer); **E25 — Extension
  Studio** (AI-assisted agent/skill/plugin development gated on contract tests +
  sandboxed evidence, publish path feeding E13). Deliverables of this pass:
  **RFC-007** (Draft — layer proposal, prior art, posture decision
  "spec-anchored, code-coupled, drift-enforced"), reference-doc extensions
  (new **§22** architecture narrative, roadmap entries **§18.7.12–§18.7.17**,
  new **v2.1 wave** in §18.9, Sumário entry), six phase docs
  (`phases/e20_spec_core.md` … `phases/e25_extension_studio.md`), the decisions
  index row, and this tracker update (story total 90 → 118 across 25 epics).
  Per-epic ADRs remain required before each epic's first story
  (`agent_guide.md` §5). Sequencing note: E22/E23's execution-dependent stories
  are gated on **E14** and **E12** — which concentrates near-term pressure on
  finishing those v2.0 epics; **E19** stays reserved for the proposed
  visual-parity audit.

- **2026-07-09** — **E17 — Frontend Redesign: Control Center Screens epic complete
  (6/6)** on `epic/e17-control-center-screens`, merged to `main` via **PR #78**. All
  seven prototype views rebuilt on the E15 shell against the E16 `/v2` endpoints:
  chat execution view (S1), plans with per-step approval gates (S2), patches
  diff/edit review (S3), sessions + config (S4), extensions hub with security
  headers/CSP hardening (S5), and flow-builder realignment (S6). Known fast-follow
  recorded in `phases/e17_control_center_screens.md`: the `/?sessionId=` reopen-as-chat
  link emitted by `SessionRow` is not yet consumed by the chat screen. This entry also
  corrects the tracker itself — the table previously still showed E17 as "Not started"
  after the merge.

- **2026-07-09** — **E18 — Control Center Front Door & Run Experience epic complete
  (5/5)** on `epic/e18-front-door`, merged to `main` via PR. **S1**: `GET /` now
  serves a content-negotiated service descriptor — JSON (`name`, `version`,
  `ui_url`, `docs_url`, `health_url`, `openapi_url`, `api.v2_base`) for API clients,
  a CSP-clean HTML pointer page for browsers; `AUTODEV_UI_URL` defaults to the first
  default CORS origin so the two cannot drift; `/` joined `_PUBLIC_PATHS` mirroring
  `/health`. **S2**: `/docs` is a hand-written page loading vendored
  `swagger-ui-dist` **5.32.8** from `/static/swagger/` (provenance + Apache-2.0
  license committed) — zero inline script, zero CDN, works offline, the global CSP
  untouched; `/redoc` removed; Starlette mounts bypassing the app-level token gate
  is documented and pinned by test. **S3**: `make run` (alias `dev`) starts both
  servers via `scripts/run_dev.sh` (prefixed logs, process-group cleanup on Ctrl-C,
  shellcheck-clean); compose `frontend` moved to a `full` profile
  (`make container-up-full`; `container-up` stays backend-only); `check-compose`
  added to `make check`; README quickstart leads with `make run` → `:3000` plus a
  ports table. Deviation from the spec recorded: `NEXT_PUBLIC_API_URL` stays
  `http://localhost:8000` (it is a browser-side variable; a service-name URL would
  break UI→API calls). **S4**: shell chrome strings routed through the i18n layer —
  new `shell.*` namespace in `frontend/locales/{en,pt-BR}.json` (the spec's
  `lib/i18n/locales.ts` pointer was stale), `navModel` labels became `labelKey`
  dot-paths, runtime key-parity test added, `components/shell/**` promoted to the
  eslint `i18next/no-literal-string` **error** gate, and a Storybook play test
  asserts the en/pt-BR chrome through the locale switcher. **S5**: README
  troubleshooting entry for the ":8000 shows JSON/404/blank docs" symptom, empty
  `frontend/chat-ui/` placeholder removed, tracker updated (0/5 → 5/5, 45 → 50
  stories).

- **2026-07-09** — Added DX epic **E18 — Control Center Front Door & Run Experience**
  (planning only, 0/5, `epic/e18-front-door`,
  `phases/e18_front_door_run_experience.md`), motivated by a field report: running
  only the backend and browsing `:8000` yields `GET /` 404 (no root route), raw JSON,
  and a blank `/docs` (the global `default-src 'self'` CSP from
  `backend/api/security_headers.py` blocks FastAPI's CDN-loaded Swagger UI and its
  inline init script). Stories: S1 root service descriptor (JSON + CSP-clean HTML
  pointer), S2 self-hosted Swagger UI assets, S3 single-command `make run` + compose
  full profile + README quickstart reshape, S4 shell string i18n, S5 docs/progress
  hygiene. A visual-parity audit of the E17 screens vs the prototype is explicitly
  deferred as a proposed **E19**.

- **2026-07-08** — **E15 — Frontend Redesign: Design Language & App Shell epic
  complete (4/4)** on `epic/e15-design-language-shell`, merged into `main` via PR.
  **E15-S3** (legacy CSS migration): purged legacy `styles/globals.css` classes from
  the dashboard, config, plans, patches, agents, and skills pages in favor of the
  token-driven `components/ui` kit; no remaining references to removed legacy
  classes under `frontend/app/` or `frontend/components/`; fixed two pre-existing
  `AppShell.stories.tsx` test failures (App Router mock for `useRouter`, and an
  `fg-3` -> `fg-2` WCAG 2.2 AA contrast fix) discovered while re-running the suite
  after the merge. **E15-S4** (i18n foundation): added a dependency-free i18n layer
  (`frontend/lib/i18n/`) — nested-key JSON dictionaries, dot-path lookup,
  `{{placeholder}}` interpolation, and a compile-time completeness check (a
  mismatched/missing `pt-BR.json` key fails the TypeScript build); externalized all
  hardcoded copy in `app/page.tsx` and `ExecutionConsolePanel.tsx`
  (`ChatLayout.tsx` was already retired by E15-S2/S3); added a `LocaleSwitcher` in
  `SidebarRail`; installed `eslint-plugin-i18next` with `no-literal-string` as a
  global warning escalated to an error for the two migrated files; documented the
  approach in `frontend/docs/i18n.md`. Gates for the epic as a whole: `npm run
  lint` (0 errors, 178 pre-existing warnings outside this epic's scope), `npm run
  typecheck` clean, `npm run test` (22/22 files, 89/89 tests), `npm run e2e`
  (12/12 Playwright tests). This satisfies RFC-006's language decision (English
  default, pt-BR complete) and clears the last E15 dependency for **E16**/**E17**.

- **2026-07-08** — Added planning-only epics **E15** (Design Language & App Shell),
  **E16** (Control-Plane API Enablement), **E17** (Control Center Screens) to readapt
  the frontend to the Execution Control Center prototype (`layout_prototype_brainstorm/`);
  scheduled before E11 kickoff. Doc-only change; RFC-006 drafted; per-epic ADRs required
  before implementation.

- **2026-07-08** — **E10 — UI/UX & Design System epic complete (4/4)** on
  `epic/e10-ui-ux-design-system`. **E10-S1**: design tokens + shadcn/ui
  component library with Storybook and a11y tests
  (`frontend/docs/design-tokens.md`). **E10-S2**: key screens (sessions,
  runs, catalogs, dashboards) with streaming. **E10-S3**: visual flow editor
  (YAML round-trip, validation, deterministic layout). **E10-S4**: pluggable
  panels / UI Extension Points (`frontend/docs/pluggable-panels.md`). Gates:
  tsc/lint/build green, 68/68 unit tests, e2e smoke on `/`, `/sessions`,
  `/flows`, `/panels` (all render, no page errors; only backend-offline
  fetch warnings). E10 lands the Beta UI anchor and unblocks **E3-S6**.
- **2026-07-07** — **E9 — APIs, Events & MCP epic complete (4/4)** on
  `epic/e9-apis-events-mcp`. **E9-S2**: run event streaming over SSE with
  cursor resume and event-type filters. **E9-S4**: MCP server exposing
  platform skills (stdio + `/v2/mcp`, least-privilege skill→tool mapping),
  MCP client + agent tool adapter with least-privilege allowlists, and an
  interop test round-tripping the stdio client against the real server
  (`backend/tests/test_mcp_interop.py`). E9-S1 (minimal Control Plane API)
  and E9-S3 (event catalog + canonical envelope) had landed earlier. This
  unblocks E8-S2 (Event Store) and the E9-S1 dependents (E10, E11, E14).

- **2026-07-06** — **E8-S1 complete; E8-S3 partial** on `epic/e8-persistence-data`.
  **E8-S1** (finishing the ADR-010 scoped slice): `backend/persistence/base.py`
  Protocol methods gained a `tenant_id: str = DEFAULT_TENANT_ID` parameter;
  `SQLiteStore`/`SQLitePlanStore` (`backend/persistence/sqlite_adapter.py`)
  and `PostgresStore`/`PostgresPlanStore`
  (`backend/persistence/postgres_adapter.py`) now enforce it — SQLite via
  `sqlite_tenant_clause()`, Postgres via `set_postgres_tenant()` + RLS; a new
  migration adds `tenant_id` (+ RLS on Postgres) to `plan_documents`/
  `plan_approvals`; `run_steps`/`plugin_events`/`score_snapshot_promotions`
  remain column-less by design, scoped transitively via `JOIN` to their
  parent's tenant. `backend/orchestrator/service.py` and
  `backend/context/providers/session_memory.py` now pass `tenant_id`
  explicitly at their Protocol call sites. **E8-S3**: added per-tenant
  pre-signed URL support and best-effort orphan cleanup
  (`backend/artifacts/store.py`, new `backend/artifacts/cleanup.py`); T2
  (artifact metadata persisted in the State Store) confirmed still missing.
  Full backend+frontend suite green (`make check`) before the epic→`main`
  PR. **Deferred**: E8-S2 (blocked on E9's event catalog), E8-S4 (blocked on
  E11); `postgres_adapter.py` split (now 713 lines) left as follow-up.

- **2026-07-06** — **E7 — Context & RAG epic complete (4/4)** on
  `epic/e7-context-rag`. **E7-S0 (prerequisite, scoped E8-S1 slice)**: added
  `backend/persistence/tenancy.py`, real up/down migration support in
  `MigrationRunner` (`Migration` pairs, `rollback_to`/`run_down`, backward
  compatible with forward-only lists), switched `PostgresStore` to the same
  versioned runner SQLite uses
  (`backend/persistence/migrations/postgres_versions.py`), and retrofitted
  `tenant_id` + RLS onto the core tables — ADR-010. **E7-S1**: real
  tree-sitter parsing for Python via a small language registry
  (`backend/repository/providers/treesitter_provider.py`), syntax-aware
  chunking (`chunking.py`), and `index()`/`reindex()`
  (`backend/repository/indexing.py`) persisting hash-deduplicated chunk
  metadata to a new tenant-scoped `code_chunks` table, wired to the job
  queue for incremental reindexing. **E7-S2**: a pluggable
  `EmbeddingProvider` (`backend/repository/embeddings/provider.py`,
  deterministic `StubEmbeddingProvider` default) and a pgvector-backed store
  (`pgvector_store.py`) — `code_embeddings` table with an HNSW cosine-distance
  index (ADR-011), dedup-by-hash batch upsert. **E7-S3**: PostgreSQL
  full-text lexical search, Reciprocal Rank Fusion, and the
  `retrieve(query, filters, budget)` contract
  (`backend/repository/retrieval/`), exposed as `GET /v2/context/retrieve`
  (`backend/api/routers/context.py`, auto-registered — API-first per root
  `CLAUDE.md`). **E7-S4**: the `ContextProvider` extension point and
  `ContextComposer` (`backend/context/`) — concurrent execution, per-provider
  timeout/isolation, weighting, and content dedup — plus two reference
  providers (files, session memory) and policy-driven context injection into
  `AgentRuntime`/`AgentRuntimeContext`. Full backend suite green (see `make
  check` output before the epic→`main` PR). **Descoped/deferred**: no formal
  CNF benchmark suite (100k-LOC indexing time, ANN p95, retrieval p95 —
  reasoned about in ADR-011 instead of measured); tree-sitter coverage is
  Python-only (registry designed for one-line language additions); the full
  E8-S1 story (mandatory tenant scoping across every repository call site,
  full negative-case RLS coverage) remains open — see the E8 row above and
  ADR-010.

- **2026-07-05** — **E5-S4 complete; E5 — Routing/Selection/Evaluation epic done (4/4)**,
  closing the loop described in reference §9.5. `backend/evals/service.py`:
  `EvaluationService.publish_snapshot()` aggregates persisted `EvalResult`s (grouped
  by agent) into a versioned, immutable `ScoreSnapshot`, emitted as
  `eval.scores.published`. `backend/routing/selector_scoring.py`: the score-weighted
  stage now really re-ranks candidates (min-max normalized cost/latency blended with
  quality per configured weights) instead of the prior no-op passthrough.
  `backend/routing/feedback.py` (new): `RoutingFeedbackService.decide_promotion`
  applies a `min_samples` hysteresis guard plus a `promote_if` regression predicate
  (reusing the existing safe expression evaluator from E5-S3, not a new parser),
  tracing every decision (`selector.policy.adjusted` /
  `selector.policy.regression_blocked`) — a rejected promotion is stored, not silently
  dropped. New `score_snapshots`/`score_snapshot_promotions` tables (dual-backend,
  additive). `POST /v2/evals/{ns}/{name}/publish`, `GET .../snapshots`; `/v2/select`
  now consults the active snapshot automatically. `default_routing_policy()` gained a
  real `score-weighted` stage so the platform default exercises the loop. ADR-008 and
  ADR-009 amended (both boundaries are touched by this story). 118 new tests. Code
  review (5 parallel angles) caught 8 real issues before commit, most notably a
  multi-version score-aggregate collision in the Selector and a `promote_if`
  field-name mismatch (`variant.cost`/`variant.latency` vs. the persisted
  `costUsd`/`latencySeconds`) that would have silently blocked every promotion.
  **Epic exit**: full backend suite green — **505/505 tests, ruff/mypy clean, 90.64%
  coverage** (gate is 60%) on `epic/e5-routing-selection-evaluation`. Epic exit
  checklist in `phases/e5_routing_selection_evaluation.md` ticked off. Ready for the
  epic -> `main` PR (not yet opened).
- **2026-07-05** — **E5-S2 complete (3/4)**. `backend/routing/selector.py`: the
  Selector pipeline — capability-matching (client-side intersection/union over
  `AgentRegistry.find_by_capability`, `registry_v2.py` untouched per ADR-008),
  cost-aware (run-budget filter + objective ranking over `AgentBudgets`), a
  documented score-weighted no-op passthrough (real snapshot wiring is E5-S4),
  and a deterministic tie-break (three chained stable sorts: agent_id -> version
  -> tie_breaker cost -> objective). `SelectRequest`/`SelectDecision`/
  `SelectorPlugin`/`ScoreSnapshot` added to `backend/routing/contract.py` per
  RFC-004 (already covered both Router and Selector); an ADR-008 amendment
  records the implementation details RFC-004 left open (model/strategy
  resolution from `AgentManifest.policy`, fail-closed `NoEligibleAgentError`,
  3-item fallback cap). `POST /v2/select` added. SDK contract bumped `1.3.0` ->
  `1.4.0`. 16 new tests (38/38 routing tests green, no regressions). Code review
  caught two real bugs before commit: capability-matching wasn't narrowing an
  already-filtered candidate pool from a prior stage, and a duplicated
  capability in a request inflated a candidate's score — both fixed with
  regression tests. **E5-S4 (feedback loop, depends on S2+S3) is the only story
  left.**
- **2026-07-05** — **E5-S1 and E5-S3 complete (2/4)**, opened `epic/e5-routing-selection-evaluation`
  from `main`. **E5-S1 (Router)**: `backend/routing/` — typed `RouteRequest`/`RouteDecision`
  contract and `RouterPlugin` protocol (§9.2), a declarative `routing.yaml` policy model
  covering the full `router:`/`selector:`/`guardrails:`/`fallback:` shape (only the
  `router.rules` pipeline stage is implemented; `embeddings`/`llm-router` are typed
  extension-point stubs pending E7), a rules executor generalizing the v1
  `RunTypeRouter`/`_ROUTE_MAP` into declarative `when`/`set` predicates with
  confidence-based short-circuit, decision tracing via the same `on_event`/`TraceEvent`
  callback style as the Reasoning Engine (not OTel spans), and `POST /v2/route`.
  RFC-004 + ADR-008 cover both the Router and (not-yet-implemented) Selector contracts
  since §9.2 documents them together. 22 tests (`test_routing_contract.py`,
  `test_routing_router.py`). **E5-S3 (Evaluation Service)**: `backend/evals/` — typed
  `eval.yaml` contract (`EvalSpec`/`EvalResult`/`Evaluator`, §9.4), a pluggable
  `Evaluator` extension point (`deterministic` via a safe AST-whitelist expression
  evaluator, never `eval()`; `llm-as-judge` via the existing `LLMProvider` stub),
  `EvalRunner`/`EvaluationService` (offline execution, quality/cost/latency metrics,
  `gate.fail_if`), a dual-backend (`SQLite`+`PostgreSQL`) `eval_results` store with a
  `UNIQUE(eval_id, eval_version, run_id)` constraint for versioned/immutable results,
  and `POST /v2/evals/run` + `GET /v2/evals/results/...`. Online A/B/canary is a typed
  stub only (no traffic-splitting infra exists yet) — in scope for a later story if
  needed. RFC-005 + ADR-009. 55 tests across 4 files. SDK contract bumped `1.2.0` ->
  `1.3.0` (additive: Router + Eval contract re-exports). Both stories ran in parallel
  (no shared files) and merged cleanly except two expected append-only conflicts
  (`backend/sdk/contracts.py` version-bump comment, `decisions/README.md` index rows).
  **E5-S2 (Selector, depends on S1)** and **E5-S4 (feedback loop, depends on S2+S3)**
  remain — both have real code dependencies on already-merged work, so unlike S1/S3
  they run sequentially, not in parallel.
- **2026-07-05** — **E4-S4 complete; E4 — Reasoning epic done (4/4)**. Added
  policy-driven strategy **selection** (`selection.py`: precedence
  default→policy-rule→manifest→flow-node→selector per §8.7, with operator-aware
  `when` predicates including ordinal levels), the **`ReasoningService`**
  (`service.py`: resolve → run → `degrade_to` fallback on `budget_exhausted`,
  with the selection/degrade decisions traced), the **Agent Runtime binding**
  (`agent_binding.py`: `AgentBudgets`→`Budget` mapping + `ReasoningInput` builder
  — the E2 seam, deliberately kept out of the already-oversized `runtime.py`), an
  `on_exceed` option on `default_reasoning_policy`, and `docs/reasoning/
  policies.md`. 6 tests (`test_reasoning_selection.py`). **E4 now delivers the
  five reference strategies, fail-closed budgets, guardrails, traced replayable
  runs, and policy-driven selection** — the Beta "Reasoning" entry item. Deep
  adoption in the default agent execution cycle (replacing the single-call step)
  is progressive (E5/E14). Ready for the epic→`main` PR.
- **2026-07-05** — **E4-S3 complete** (advanced reasoning strategies). Added
  **Reflection** (`autodev/reasoning-reflection` — draft→self-critique→revise,
  bounded by `max_revisions`, early-exit on approval) and **Debate/Tree-of-
  Thought** (`autodev/reasoning-tot` — expand `branches`, score, keep top
  `beam`) to `backend/reasoning/strategies/`, completing the five reference
  strategies of §8.9. Fan-out is **budget-bounded / fail-closed** (a wide ToT
  search stops at the step ceiling, verified). `builtin_strategies()` now
  returns all five. 4 tests (`test_reasoning_advanced.py`);
  `docs/reasoning/contract.md` updated.
- **2026-07-05** — **E4-S2 complete** (reference reasoning strategies). Added
  `backend/reasoning/strategies/`: **ReAct** (`autodev/reasoning-react` —
  Thought→Action→Observation with mediated tool calls), **Plan-and-Execute**
  (`autodev/reasoning-plan-execute`), and **native tool-calling**
  (`autodev/reasoning-native-tools`) — three of the five reference strategies in
  §8.9 — plus `register_builtin_strategies`. All run through the Engine on the
  offline stub provider, are swappable without caller changes, and honor
  fail-closed budgets (verified by a never-terminating ReAct loop). 5 tests
  (`test_reasoning_strategies.py`); `docs/reasoning/contract.md` updated.
  Reflection + Debate/Tree-of-Thought are E4-S3.
- **2026-07-05** — **E4-S1 complete** (Reasoning Strategy contract + Reasoning
  Engine). Added `backend/reasoning/`: the typed, SemVer-versioned contract
  (`contract.py` — `ReasoningInput`/`ReasoningOutput`, the `ReasoningContext`
  mediator, `ReasoningStrategy`, immutable `Usage`, `Budget`, `TraceEvent`,
  guardrail/exception types, and the `reasoning-strategy.yaml` manifest); the
  fail-closed **Reasoning Engine** (`engine.py` — mediates every LLM/tool call,
  debits the budget, emits an ordered trace via an `on_event` Event Bus hook,
  enforces guardrail `block`/`warn`/`repair_once`, and terminates with the
  correct `stop_reason`); the SemVer strategy registry (`registry.py`); and the
  declarative `reasoning-policy.yaml` model (`policy.py`). Published schemas
  (`reasoning-strategy.schema.json`, `reasoning-policy.schema.json`); SDK
  contract export bumped to `1.2.0`; RFC-003 + ADR-007 (async contract / sync
  host; engine-owned fail-closed budgets; single-`tokens` budget model);
  `docs/reasoning/contract.md`; and 12 contract tests
  (`test_reasoning_contract.py`, incl. the fail-closed no-effect-past-ceiling
  case). The `reasoning.strategy` extension point was already present in the
  plugin catalog. Process note: implementation was to be handed to Codex per the
  user's request, but the Codex CLI workspace was out of credits; with the
  user's approval E4-S1 was implemented directly in Claude instead.
- **2026-07-05** — **E3 Alpha slice verified complete** and closed for Alpha
  (S1-S5 Done; flow suite 38/38 green). **E3-S6 (visual flow editor) formally
  deferred to Beta** — it depends on **E10** (Design System, Not started) per
  `phases/e3_orchestration_engine.md` and the Beta entry list, so no S6 work is
  achievable until E10 lands. No code change in this entry (E3 was already
  Alpha-complete; this reconciles the epic-table status that still read
  "In progress"). **E4 — Reasoning started**: opened `epic/e4-reasoning` from
  `main`; executing E4-S1..S4 per `phases/e4_reasoning.md` and reference §8.

- **2026-07-05** — Planning-only, no implementation: added **E14 — Real Task
  Execution & Governed Autonomy** (Beta, 7 stories) to close the gap between
  generated plans and real action — today `execute_plan`
  (`backend/orchestrator/service.py`) only marks steps completed without
  creating files, applying patches, or running commands. E14 covers: a real
  Task Executor (`ExecutionAction`/`ExecutionResult`, E14-S1); a fail-closed
  permission/policy engine (E14-S2); three execution modes — approval, auto,
  hybrid with the 3-option dynamic-grant prompt (E14-S3); sandbox-backed
  command/patch/validation runners built on the existing
  `backend/validation/sandbox.py::SandboxRunner` (E14-S4); governed Web UX
  (E14-S5); a governed interactive shell, `autodev --shell` (E14-S6); and
  `autodev` CLI packaging/install (E14-S7). Extends
  `docs/architecture/v2_platform_reference.md` (new §12.7-§12.9, renumbered
  §12.7 Acceptance Criteria to §12.10 with added bullets, new §18.7.8, and
  updates to §18.5/§18.8/§18.9) and adds
  `phases/e14_real_execution_governance.md`. An RFC + ADR are required before
  E14-S1 implementation starts (new public contracts, per `agent_guide.md`
  §5).
- **2026-07-05** — **E3-S3 complete**: per-step checkpoints (state persisted after
  every step), opt-in retry/backoff (default 1 attempt, exponential capped at 1 h,
  backoff sleeps budget-checked), crash recovery via `resume_run` (incl.
  complete-step/checkpoint crash-window reconciliation), and deterministic replay
  via `replay_run` under the ADR-005 determinism boundary (JSON-canonical node
  outputs; divergences reported, never raised). `backend/flows/checkpoint.py` +
  `activation.py`; ADR-005.
- **2026-07-05** — **E3-S4 complete**: human-in-the-loop — durable `waiting_human`
  pause (`flow.run.paused`), decision API (`pending-human`, `human-decision`,
  `human/expire`) with actor recorded on `flow.human.decision.recorded`, operator
  edits merged into run state, timeout routing through `on: timeout` edges, 401
  when a bearer token is configured. `backend/flows/human.py` + `pause.py`.
- **2026-07-05** — **E3-S5 hardening** (post-merge review fixes): map-node input
  bindings are no longer pre-rendered by the engine (the `item` root only exists
  per branch), and parallel map branches take in-flight budget reservations so
  they cannot jointly overspend the parent (ADR-006 amendment).
- **2026-07-02** — Created `docs/v2_platform/` (this tracker, per-epic phase docs,
  process/manifest templates, agent guide, decisions log, documentation-rebuild
  playbook). No implementation work started. Baseline captured from
  `docs/architecture/v2_platform_reference.md` and `docs/feature_matrix.md`.
- **2026-07-02** — Packaged and tagged the v1 architecture as `v1` (published GitHub release) (see
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
- **2026-07-03** — Completed E0-S3: implemented PostgreSQL-backed sessions/runs/
  messages/plans, selected it from `DATABASE_URL`, added local Compose Postgres
  support, recorded ADR-001, and published the backup/restore runbook.
- **2026-07-03** — Completed E0-S4: added configured OpenTelemetry request and
  run-step spans, non-PII trace correlation attributes, Prometheus 5xx counters,
  and `docs/ops/observability.md`.
- **2026-07-03** — Completed E0-S5: added default HTTP security headers, an
  opt-in HSTS setting, dependency-free `run_secret_scanning`, a backend CI
  secret/SCA gate, and `docs/security/baseline.md`.
- **2026-07-04** — Completed E0-S6 and closed E0 after auditing existing
  settings/job queue work: kept local mode dependency-free, implemented Redis
  queue/cache/locks with lock contention coverage, added local and MinIO/S3
  artifact stores with recoverable patch/log objects, wired Redis/MinIO into the
  production-like Compose profile, and published `docs/ops/storage.md`.
- **2026-07-04** — Completed E1-S1: added the typed plugin extension-point catalog,
  `plugin.yaml` dataclasses and validator, the published JSON schema, RFC-001,
  ADR-002, and `docs/plugins/manifest.md`.
- **2026-07-04** — Completed E1-S2: added Plugin Host discovery from directories
  and entry points, durable install/enable/disable/uninstall lifecycle state,
  `hostApi` compatibility rejection with reasons, isolated load failures, and
  documented `plugin.installed`/`plugin.enabled`/`plugin.disabled` events.
- **2026-07-04** — Completed E1-S3: added the default-deny fs/net/exec/secrets
  permission model, brokered Host API access, in-process import sandbox checks,
  `plugin.permission.denied` audit events, denial-by-permission tests, and
  `docs/plugins/permissions.md`.
- **2026-07-04** — Completed E1-S4: added SemVer-versioned Python SDK contracts,
  a minimal TypeScript contract stub, `sdk new plugin` scaffolding through the SDK
  and main CLIs, the plugin contract-test harness, a runnable example plugin, and
  `docs/sdk/write-your-first-plugin.md`.
- **2026-07-04** — Completed E1-S5 and closed E1: added the active-plugin registry,
  `/v2/plugins/active` query API with `schemaVersion`, registry consistency after
  enable/disable, safe dev hot-reload rollback, and `docs/plugins/registry.md`.
- **2026-07-04** — Completed E2-S1: added the versioned `agent.yaml` manifest
  validator, strict typed IO validation with safe default budgets, the initial
  capability vocabulary in ADR-003, the published SDK contract surface, schema file,
  and `docs/agents/manifest.md`.
- **2026-07-04** — Completed E2-S2: added the durable Agent Registry, SemVer
  resolution with multiple versions, rankable capability search, deprecation
  signaling, Plugin Host sync for enabled agent manifests, `/v2/agents/catalog`, and
  `docs/agents/registry.md`.
- **2026-07-04** — Completed E2-S3: added the Agent Runtime execution cycle with
  fail-closed token/cost/step/tool-call budgets, strict input/output validation,
  output denylist guardrails, per-step trace emission, token/cost metrics, and
  budget-overrun and guardrail tests.
- **2026-07-04** — Completed E2-S4: added permissioned tool/skill mediation on the
  Agent Runtime context, default network denial, the offline stub LLM provider and
  provider protocol, per-call token/cost/tool metering by run and tenant, mocked real
  provider coverage, and `docs/agents/runtime.md`.
- **2026-07-04** — Completed E2-S5 and closed E2: packaged
  `autodev/agent-coder` as an installable agent plugin, captured the v1 fallback
  baseline, added runtime parity coverage, registered the plugin through the Plugin
  Host and Agent Registry, included the SDK example, and marked the E2 exit checklist
  complete.
- **2026-07-04** — Documentation alignment + governance pass (out-of-band, per the
  E1/E2 per-epic triggers in `documentation_rebuild.md`; not a wave-gate rebuild —
  Alpha has not exited): refreshed root docs (`README`, `DESCRIPTION`, `CHANGELOG`
  Unreleased section, `AGENTS.md`, `AGENT.md`), corrected
  `docs/feature_matrix.md` (PostgreSQL no longer a stub; new Plugin System and
  Agent Framework v2 sections), annotated superseded `docs/roadmap.md` releases,
  added historical/status banners to superseded architecture and implementation
  docs, and documented E1-S3 permission isolation in `docs/security.md`. Also
  introduced repo governance: `CONTRIBUTING.md` (epic/story branching model,
  docstring + type-hint standards, story-scoped vs full-suite testing policy),
  `agent_guide.md` §3–§4 (mandatory from E3 onward), PR/issue templates,
  Apache-2.0 `LICENSE` + `NOTICE` + `CITATION.cff`, and opt-in parallel testing
  (`make test-backend-parallel`, suite validated 285/285 at ~2× speed).
- **2026-07-05** — Completed E3-S1: added the `flow.yaml` manifest contract
  (`backend/flows/` typed model, parser, structural graph validation, safe
  expression language for predicates/bindings), the published
  `flow.schema.json`, the SDK `FlowManifest` export (contract 1.1.0), RFC-002,
  ADR-004, and `docs/flows/spec.md`. Epic branch
  `epic/e3-orchestration-engine` opened per CONTRIBUTING.md §2.
- **2026-07-05** — Completed E3-S2: added the Flow Engine (declaration-order
  edge routing with safe predicates, fail-closed budgets + engine step cap),
  durable `flow_runs`/`flow_steps`/`flow_events` tables (SQLite WAL tuning
  validated by a 100-concurrent-run test; PostgreSQL dialect), the versioned
  FlowRegistry, pluggable node handlers (agent via the E2 registry/runtime,
  skill/tool callable registry, conditional), trigger normalization with
  declared-trigger enforcement (message/webhook/event/cron matcher), ordered
  lifecycle events, the `/v2/flows` API, per-step OTel spans,
  `docs/flows/engine.md`, and an end-to-end test running the
  `autodev/agent-coder` plugin from a declarative flow.
- **2026-07-05** — Completed E3-S5: added composite nodes — `subflow` handler
  (child run of a registry-resolved flow with `parent_run_id` linkage and
  `childRunId` in the parent step output) and `map` handler (bounded parallel
  fan-out with per-item `item` bindings, input-ordered `collect` reduce) in
  `backend/flows/composite.py`; budget propagation per ADR-006 (child budget =
  min(child manifest, parent remaining), aggregate fail-closed with branch
  cancellation, `budget_cap` on `start_run`), shared budget arithmetic in
  `backend/flows/budgets.py`, a composite-depth guard, hierarchical run
  queries (`list_runs(parent_run_id=...)`), and 10 new tests.
- **2026-07-04** — API-first made an explicit principle (out-of-band, docs-only):
  added principle 2.13 "API-first" to `v2_platform_reference.md` §2 (the Control
  Plane API is the single point of entry; Web UI/CLI/MCP are clients, never touch
  internals directly), renumbered the verification table to §2.14 with a matching
  row, and cross-referenced it from `agent_guide.md` §6, root `CLAUDE.md`, and
  `CONTRIBUTING.md` §3. The platform was already built this way; this made the rule
  explicit and verifiable rather than implicit.
- **2026-07-04** — E0-E2 docstring/type-hint compliance audit (out-of-band, not a
  new story): reviewed all 63 files added/changed for E0-E2 (per
  `git diff v1..HEAD -- backend/`) against `CONTRIBUTING.md` §3. Added missing
  Google-style docstrings and/or type hints to 58 files; 5 pure re-export
  `__init__.py` files were already compliant. Verified `lint-backend` (ruff),
  `typecheck-backend` (mypy), and `test-backend` all green (285/285 tests,
  matching the prior baseline — no regressions). Flagged, not fixed here (would
  require a real refactor, out of scope for a docstring/type-hint pass):
  `backend/orchestrator/service.py` (856 lines) and
  `backend/persistence/postgres_adapter.py` (551 lines) exceed the 500-line file
  limit — both were already over/at the cap before this pass and grew slightly
  from added docstrings. Follow-up: split each into smaller modules.
