# v2 Platform — Implementation Progress

> Living tracker for the v2.0 platform refactor described in
> `docs/architecture/v2_platform_reference.md`. Update this file whenever a story or
> epic changes state, whenever a wave gate is cleared, and whenever an ADR/RFC is
> added (cross-check `docs/v2_platform/decisions/README.md`). This file is the single
> place to look to answer "where are we on the v2 rewrite?" without re-reading the
> 6600-line reference document.

**Last updated:** 2026-07-05 (E3 Alpha slice S1-S5 complete; S6 deferred to Beta with E10)

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
points only — they do not satisfy the v2 contracts. Remaining Alpha anchor
work: **E3** (graph/checkpointing/human-in-the-loop), **E8-S1/E8-S2**,
**E9-S1**, and **E12-S1**. **Next action: pick up E3 after reading
`phases/e3_orchestration_engine.md` and `agent_guide.md` §1-4 (the branching
and quality rules in §3-4 are mandatory from E3 onward).**

## Epic status

| Epic | Name | Wave | Status | Stories | Depends on | Doc |
| --- | --- | --- | --- | --- | --- | --- |
| E0 | Foundations & Hardening | Alpha | Done | 7/7 | — | [phases/e0_foundations_hardening.md](phases/e0_foundations_hardening.md) |
| E1 | Plugin Core & SDK | Alpha | Done | 5/5 | E0 | [phases/e1_plugin_core_sdk.md](phases/e1_plugin_core_sdk.md) |
| E2 | Agent Framework | Alpha | Done | 5/5 | E0, E1 | [phases/e2_agent_framework.md](phases/e2_agent_framework.md) |
| E3 | Orchestration Engine | Alpha/Beta | In progress | 5/6 | E0, E2 | [phases/e3_orchestration_engine.md](phases/e3_orchestration_engine.md) |
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

Total: **17/64 stories complete** across 14 epics.

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
