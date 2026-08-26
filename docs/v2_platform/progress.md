# v2 Platform — Implementation Progress

> Living tracker for the v2.0 platform refactor described in
> `docs/architecture/v2_platform_reference.md`. Update this file whenever a story or
> epic changes state, whenever a wave gate is cleared, and whenever an ADR/RFC is
> added (cross-check `docs/v2_platform/decisions/README.md`). This file is the single
> place to look to answer "where are we on the v2 rewrite?" without re-reading the
> 6600-line reference document.

**Last updated:** 2026-08-26 (**E50 complete — 4/4, PostgreSQL Schema,
Migrations, Tenancy & RLS**, on `epic/e50-postgres-schema-migrations-rls` —
closes the schema half of the gap `postgres_production_completeness.md`
identified: the 13 domain tables (quotas, secrets, execution policy,
environments, plan step state) that were created by ad hoc
`CREATE TABLE IF NOT EXISTS` outside `MigrationRunner`, untracked by
`schema_version`, and without Row-Level Security. **E50-S1/S2/S3** append
versioned PostgreSQL migrations 8-10 (`POSTGRES_STORE_MIGRATIONS`) creating
all 13 with PostgreSQL types (`JSONB`/`TIMESTAMPTZ`/`BIGINT`) and
tenant-first keys/indexes; `plan_step_state` additionally gains `tenant_id`
and a foreign key to `plan_documents` on **both** backends (SQLite
backfills existing rows to `DEFAULT_TENANT_ID` via an `ADD COLUMN ...
DEFAULT` statement). **E50-S4** applies `ENABLE`/`FORCE ROW LEVEL SECURITY`
plus a `<t>_tenant_isolation` policy to all 13 via a shared
`_apply_tenant_rls()` generator (migration 11), and extends
`backend/quotas/migrations.py`'s `--check` verifier to cover them on
PostgreSQL. The 13 tables' *stores* are still SQLite-only — reads/writes
land in E51-E55 — so this epic is schema-only by design (out of scope: no
push/PR without explicit authorization was overridden by the requesting
session for this epic). Live cross-tenant RLS enforcement proof against a
running PostgreSQL is deferred to E57 (CI & Real PostgreSQL E2E, not yet
started); this epic's tests assert migration DDL shape via the existing
`FakeConnection` pattern, consistent with every other PostgreSQL migration
test in this codebase to date.)
Previous entry: 2026-08-21 (**Planning-only: added the E48-E60 PostgreSQL
Production Completeness program — 13 Beta-hardening epics, 46 planned
stories**, on `main`. The `prod` profile requires PostgreSQL
(`backend/config/settings.py:332-336`) while four domain stores raise
`ValueError` on a PostgreSQL URL and a fifth silently writes
`./autodev_plan_step_state.db` — quotas, secrets, execution policy, and
execution environments cannot be constructed in production today. See
`postgres_production_completeness.md` and the changelog entry.)
Previous entry: 2026-08-21 (**E44 complete — 5/5, Beta-hardening backend
efficiency**, on `epic/e44-persistence-efficiency` — Control Plane
read/write cost no longer grows with data volume: `GET /v2/turns/{id}` is a
2-statement primary-key lookup instead of a sessions × runs scan, session/
run/turn listings paginate in SQL at a fixed 3 statements per page, message
append reads one row instead of the whole conversation, and run-step
persistence upserts by position instead of DELETE + full re-insert
(O(N²) → O(N) writes per run). See the changelog entry and
`phases/e44_persistence_efficiency.md`.)
Previous entry: 2026-08-21 (**Planning-only: added Beta-hardening epics
E44–E47 — backend efficiency & simplification, 18 planned stories**, on
`main`.)
Earlier: 2026-08-19 (**E35 complete — 3/3, v2.0-beta wave
substantially complete**, branch `epic/e35-beta-readiness-gates` (branched
from `main` after E34 merged via PR #107) — turns the v2.0-beta gate from a
claims checklist into an evidence-backed one. **E35-S1** split §18.9's
combined isolation/secrets criterion into three separately assertable
criteria (10 isolation/E32, 11 secrets/E33, 12 clean-install-and-upgrade/
E34) and added a 12-criterion evidence map
(`docs/v2_platform/beta_gap_analysis.md` §11, "fact vs. recommendation"
discipline per E35-S1-T3): 7 criteria **Atendido** with named evidence, 2
**Parcial**, 3 honestly **Aberto** (hybrid-retrieval benchmark never run
against a live environment, no numeric streaming-latency assertion, no
staging environment for restore validation) — named gaps, not silently
presumed closed. **E35-S2** delivered `docs/v2_platform/beta_acceptance_flow.md`,
an executable checklist composing the central plan→approve→code→validate→
evaluate flow plus four negative paths (permission denied, budget
exhausted, isolation violation, secret revoked) from real, already-tested
evidence — no new automated test, since the pieces already exist and this
is what strings them into one rehearsal. **E35-S3** resolved the open-
decisions register (ADR-013/014/015 all Accepted within their own epics,
kept traceable with options/owner/decide-by rather than deleted), added a
formal Beta risk register (isolation escape, secret leak, failed upgrade,
runaway execution, each mapped to its mitigating stories), and three
incident runbooks extending the E11 set
(`docs/v2_platform/runbooks/e35_*.md`): isolation-violation containment
(`AUTODEV_EXECUTION_ENVIRONMENT_BACKEND=unavailable` as a config-level kill
switch), secret rotation under suspected leak, and the three
`autodev upgrade` failure modes with their correct restore action. Also
fixed accumulated doc drift found along the way: `decisions/README.md`
still listed ADR-013/014/015 as Proposed, and E33's own progress.md entry
still read "Not merged to `main`" after PR #106 had already landed it.
E35 introduces no new extension points — it governs evidence for existing
ones, per its own phase doc. Not yet merged to `main`. Previous entry:
2026-08-18 (**E34 complete — 3/3**, branch
`epic/e34-packaging-global-install` (branched from `main` after E33 merged
via PR #106) — the Beta packaging/distribution slice: ADR-015 (Global
Installation Strategy) resolved Proposed -> Accepted, choosing a hybrid of
the already-strategy-agnostic `[project.scripts] autodev = "backend.cli:main"`
console-script entry point (works identically under `pip`/`pipx`/`uv tool`)
for the CLI, plus the existing `docker-compose` bundle for self-host — no
new packaging mechanism was needed, only version reporting
(`autodev --version` -> `backend/ops/version.py`, package version + best-effort
commit/build-date) and `scripts/verify_clean_install.sh` (builds a wheel,
installs into a fresh venv, runs from a temp dir outside the repo). New
`backend/ops/` package (distinct from `backend.config`/`backend.persistence`,
matching E34's packaging/bootstrap/upgrade ownership boundary vs E14's CLI
UX): `doctor.py` (typed, ordered preflight checks — settings, port,
project_root, database, storage_backend, skipping dependents when `settings`
itself fails) and `bootstrap.py` (same preflight fail-closed, then
initializes the configured state store via the existing idempotent migration
runner — never handles a plaintext secret value, by design). Storage posture
(SQLite/local vs PostgreSQL/s3) turned out to already be explicit, fail-closed
configuration (`Settings.validate_profile`, a pydantic `model_validator`) —
E34-S2 documented it rather than reimplementing it. `MigrationRunner.run_pending()`
(shared by SQLite and PostgreSQL) now raises `SchemaVersionMismatchError`
and refuses outright when a database's recorded schema version is newer than
the installed code's migration list knows — the E34-S3 compatibility check,
protecting every caller, not just the new `autodev upgrade` command, which
backs up the state/artifact stores first (reusing the E8-S4 `BackupManager`
contract) and only then attempts to migrate; rollback posture is documented
as restore-from-backup with the existing E8-S4 tooling rather than a new
mechanism, and `--target-version` surfaces a best-effort `CHANGELOG.md`
excerpt as groundwork for the GA v1->v2 upgrade requirement (E13). Docs:
`docs/execution/cli-install.md` (extended), `docs/execution/upgrade.md`
(new), `docs/v2_platform/decisions/ADR-015-global-install-strategy.md`
(Proposed -> Accepted). Scope reduction stated honestly: no installer script
(`curl | sh`) and no standalone/native binary — `pip`/`pipx`/`uv` plus the
wheel-based clean-install verification cover the documented path; the
v2.0-beta gate's actual clean-environment-install checklist row (§18.9) is
left to E35-S1-T1 (Beta Readiness Gates & Evidence), which owns expanding
that gate with the E32/E33/E34 criteria — not duplicated here. Merged to
`main` via PR #107 (2026-08-19). Previous entry: 2026-08-18 (**E33 complete — 3/3**, branch
`epic/e33-secrets-credential-governance` (branched from
`epic/e32-isolated-execution-beta`, which is not yet merged to `main`) —
the Beta secret layer: a scoped-reference secret store
(`backend/secret_store/`, named to avoid shadowing Python's stdlib
`secrets` module) that never returns a value over any API, Fernet-based
envelope encryption reusing the primitive already established for browser
refresh tokens (ADR-014 accepted: database-encrypted-at-rest, contract-first
behind `SecretBackendKind`); injection into E32 execution environments via
the existing `EnvironmentProfile.env_allowlist` gate, resolved fresh on
every `bind_environment()` call and handed to the sandbox as process env
(`ValidationJob.extra_env`) — never through model context or artifacts;
exact-value redaction of collected logs/diffs before persistence plus a
process-wide safety net inside `emit_event()` itself, so every event
producer is protected; a typed `secret.leak.suspected` audit event for a
task that echoes a secret; and rotation that takes effect on the next
provision with revocation failing resolution closed, both durably audited
(`secret.created`/`.rotated`/`.revoked`/`.resolved`, catalog 46 → 51).
`secret:use`/`secret:manage` RBAC scopes mirror the `quota:read`/
`quota:admin` split; `/v2/secrets` and `autodev secrets` are the REST/CLI
surfaces, values only ever accepted write-only (stdin for the CLI, never
a flag). Docs: `docs/security/secrets.md`,
`docs/v2_platform/decisions/ADR-014-secret-store-format.md` (Proposed ->
Accepted). Scope reduction stated honestly: Postgres RLS-backed storage
and a true external KMS/vault backend are deferred behind the swappable
`SecretBackendKind` contract; adding the "no plaintext secrets" row to the
v2.0-beta gate checklist (§18.9) is E35-S1-T1's job, not E33's — E33
supplies the evidence (redaction + audit tests), not the checklist edit.
Merged to `main` via PR #106 (2026-08-18), together with the E32 commits it
was branched from (doc-drift fix: this entry previously read "Not merged to
`main`", written before PR #106 landed). Previous entry: 2026-08-18 (**E32
complete — 4/4**,
branch `epic/e32-isolated-execution-beta` — the Beta cut of the isolated
execution environment: a backend-agnostic `EnvironmentBackend` abstraction
(`backend/environments/`) with configuration-only selection (unset →
`hardened_container`, the ADR-013-accepted default built on the existing
`SandboxRunner`; unrecognized → the fail-closed `UnavailableBackend`
sentinel); default-deny network egress and workspace-scoped filesystem
access, both typed and durably audited; a provision → execute → collect →
teardown lifecycle wired into `OrchestratorService._process_tasks` (one
environment per dispatch batch, torn down on completion or pause,
TTL-reaped if orphaned) with a per-tenant concurrency ceiling; artifact
egress (stdout/diff) through the E0/E8 artifact store, best-effort so a
storage failure never fails the run; and an additive `environment` field
on every `ExecutionResult` plus four new catalog events (42 → 46) so an
auditor can reconstruct which backend/profile a run used from durable
records alone. Scope boundary recorded in
`docs/environments/beta_isolation.md`: no plugin-facing
`execution_environment` extension point yet, and workspace provisioning
binds to the existing `project_root` rather than a fresh ref-pinned
checkout — both deferred to E28 alongside the microVM-class backend and
snapshot mechanism that would first exercise them. `epic/e14-real-execution-governance`
merged to `main` via PR #104 (2026-08-17) beforehand — see the previous
entry below for E14's own scope. Previous entry: 2026-08-17 (**E14 kicked
off — E14-S1 (Real Task Executor) complete, E14 now In progress · 1/7** —
branch `epic/e14-real-execution-governance`. `execute_plan` performs real work for
the first time: `TaskExecutor`/`InProcessActionRunner`
(`backend/execution/`) reuse the existing patch engine and v1 sandbox
runner; RFC-009 + ADR-021 accepted. See the Changelog entry below and
`docs/execution/engine.md`. Not merged to `main`.) Previous entry: 2026-08-17
(**Gap-closure pass, no new epic** — branch
`epic/gap-closure-alpha`. Closed the E17 S1↔S4 reopen-as-chat fast-follow, four
of E7's five deferred story-DoD items (indexing + context spans, language and
fusion docs, a retrieval recall/latency benchmark harness), and walked the
**v2.0-alpha wave gate**, which now has named evidence on all five criteria and
**is met**. Reconciled two tracker lies: the E2 phase doc still read "In
Progress 5/6" after E2-S6 merged, and **E11 was tracked as `Not started 0/4`
while S1/S2/S4 were already merged on its epic branch** (3/4, not on `main`).
Three open defects recorded in the doc-drift ledger, all needing a decision
rather than a quiet fix: the plugin import sandbox denying transitive host
imports (D2), `ContextComposer.compose` blocking past its own timeout (D3), and
the E11 branch state (D1). Previous entry: 2026-08-05 (**E2 complete 6/6** —
E2-S6 delivers the provider-neutral model gateway: agents select models via additive schema 2.1, precedence is execution override → agent manifest → global `LLM_MODEL`, and capability checks, governed fallback, call/token/cost ceilings, and telemetry are enforced by AutoDev-owned contracts (ADR-016). Public configuration and tested limitations: `docs/agents/model_gateway.md`. **Caveat:** the story branch was not reviewed end to end; the review loop was stopped by explicit decision after five fix rounds — see `handoffs/e2_s6_model_gateway.md`.) Previous entry: 2026-08-05 (**E2-S6 corrective story in progress — E2 temporarily 5/6**: ADR-016 selects an AutoDev-owned provider-neutral model gateway boundary; immutable contracts and additive validated 2.1 agent model configuration are landing without changing 2.0 manifests. Previous entry: **Planning-only: added the v2.3 Platform Excellence wave — epics E36-E40** for document authority + SDD operating model, context-independent harness/looping excellence, SOTA evidence + capability benchmark, product modes + agentic security + minimum FinOps, and architecture fitness + local-first degradation. Previous entry: **Beta hardening wave planned — epics E32–E35
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


## Planning authority

| Question | Authoritative source | Notes |
| --- | --- | --- |
| Architecture principles and stable contracts | `docs/architecture/v2_platform_reference.md` | Normative for subsystem boundaries, extension points and NFRs. |
| Implementation status, current wave, next action and known drift | `docs/v2_platform/progress.md` | This file wins for execution sequencing and tracker status. |
| Epic/story scope and acceptance criteria | `docs/v2_platform/phases/e<N>_*.md` | Detailed story scope; status headers must match this tracker. |
| ADR/RFC decisions | `docs/v2_platform/decisions/` | Decisions win over older prose when accepted; proposed decisions must be called out. |

### Doc drift ledger

When a contributor finds a conflict between the reference, tracker, phase docs,
AGENTS.md or implementation evidence, record it here before changing execution
order.

**Open entries (2026-08-17 gap-closure pass, branch `epic/gap-closure-alpha`):**

| # | Entry | Evidence | Status |
| --- | --- | --- | --- |
| D1 | **E11 was tracked as `Not started 0/4` while three of its stories were already merged on its epic branch.** `epic/e11-observability-security-multitenant` carries E11-S1 (observability stack), E11-S2 (RBAC + authentication) and E11-S4 (execution security + runbooks), and `story/e11-s3-multitenant-quotas-budgets` has three commits on top. None of it is on `main`. The tracker's "Next action: E11-S1" was therefore pointing at finished work. | `git log main..origin/epic/e11-observability-security-multitenant` | **Resolved (2026-08-17).** E11-S3 finished (ADR-019) and the epic → `main` PR merged; E11 is Done 4/4 on `main`. |
| D2 | **The in-process plugin import sandbox denies transitive *host* imports.** `PluginPermissions.import_sandbox` (`backend/plugins/permissions.py`) guards `builtins.__import__` against `NETWORK_MODULES` without distinguishing a plugin's own network use from an import of `backend.*` that transitively reaches `urllib`. From a cold process the reference plugin `autodev/agent-coder` is quarantined with "network imports require permissions.network.egress"; a running server is unaffected because the host modules are already in `sys.modules`. This also makes `test_flows_api.py::TestAgentFlowEndToEnd` order-dependent — it fails when run alone. | `backend/tests/integration/test_alpha_gate_flow_replay.py` (module docstring reproduces it); `pytest "backend/tests/unit/flows/test_flows_api.py::TestAgentFlowEndToEnd"` in isolation | **Open — needs a decision.** Narrowing the guard changes a security boundary, so it is not being changed unilaterally: it wants an ADR on what the in-process import sandbox is meant to protect against, given that the `in-process` loader exists precisely to let plugins import the host. |
| D3 | **`ContextComposer.compose` blocks past its own per-provider timeout.** Its docstring promises a slow provider "never ... blocks the other providers' results", but the surrounding `with ThreadPoolExecutor(...)` runs `shutdown(wait=True)` on exit, so the call does not return until every worker finishes. | `backend/tests/unit/observability/test_context_indexing_tracing.py::test_timed_out_provider_span_records_its_real_duration` (pins the behavior, does not fix it) | Open — recorded in `phases/e7_context_rag.md`; fix belongs to an E7 follow-up or E26. |

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

## Wave status: Alpha and Beta complete — GA (E13) is next

**Current wave: GA.** Both the v2.0-alpha and v2.0-beta waves have exited and
**`v2.0-beta` is published as a GitHub pre-release** (2026-08-20, targeting
`main`). 22 epics are Done — E0-E12, E14-E18 and the Beta hardening set
E32 (isolated execution), E33 (secrets & credential governance), E34
(packaging & global install) and E35 (readiness gates & evidence).

It is a **pre-release, not a signed-off wave**: three of the twelve Beta exit
criteria remain open because they need a live environment the wave did not own
— the hybrid-retrieval p95/recall benchmark, a numeric run-streaming start
latency assertion, and staging backup/restore RPO/RTO validation. Two more are
partial (no single composed end-to-end rehearsal; WCAG is component-level
only). See the [Beta wave exit gate](#v20-beta--full-platform-in-controlled-production)
below and `beta_gap_analysis.md` §11 for the evidence map. Closing those three
is GA-wave work.

**E41 — Real Code Generation & Agent-Directed Execution is now complete
(5/5, 2026-08-21)**, closing the gap this pre-release itself surfaced: a
goal now produces real files on disk and real agent-declared commands run
in the E32 sandbox, with one bounded self-repair retry on test failure —
see the changelog entry below and
[phases/e41_real_code_generation_execution.md](phases/e41_real_code_generation_execution.md).

**E44 — Persistence Read/Write Efficiency is now complete (5/5,
2026-08-21)**, the first of the four Beta-hardening backend-efficiency
epics: every hot Control Plane read/write path is now constant-cost in the
tenant's data volume — see the changelog entry and
[phases/e44_persistence_efficiency.md](phases/e44_persistence_efficiency.md).

**E45 — Runtime I/O Efficiency is now complete (5/5, 2026-08-21)**: the
job worker blocks on `BLPOP` with graceful shutdown instead of busy-polling,
completed job records carry a configurable TTL/eviction window instead of
growing forever, the Event Bus's `subscribe()` returns an unsubscribe token
so the SSE endpoint frees its subscriber on disconnect, `replay_from` is
offloaded off the event loop and both bus backends bound their retained
stream/partition length, and repository indexing prunes ignored
directories during traversal and persists in batched, `executemany`
transactions — see
[phases/e45_runtime_io_efficiency.md](phases/e45_runtime_io_efficiency.md).

**E47 — Backend Structural Consolidation is now complete (5/5, 2026-08-21)**,
the last of the four Beta-hardening backend-efficiency epics — see the
changelog entry and
[phases/e47_backend_structural_consolidation.md](phases/e47_backend_structural_consolidation.md).

**E48 — PostgreSQL Runtime with pgvector is now complete (4/4, 2026-08-22)**,
the first of the PostgreSQL Production Completeness epics: the `prod`/
`postgres` Compose profiles now ship `pgvector/pgvector:0.8.3-pg16`
(ADR-024, Accepted), extension provisioning is a separate idempotent step
that fails closed with an actionable message rather than requiring
`CREATE EXTENSION` privilege, and `backend/ops/doctor.py` plus a new `GET
/readiness` endpoint fail closed on server version, extension presence,
extension usability, and HNSW index validity before the API accepts
traffic — see the changelog entry and
[phases/e48_postgres_runtime_pgvector.md](phases/e48_postgres_runtime_pgvector.md).

**E49 — Shared SQL Persistence Infrastructure is now complete (4/4,
2026-08-23)**: the eight dual-dialect stores that each hand-rolled
`_is_postgres`/`{p}`-template placeholder substitution now share one
implementation (`backend/persistence/contract.py`, ADR-025), and an
automated guard blocks a new domain module from opening a database
connection directly — see the changelog entry and
[phases/e49_shared_sql_infrastructure.md](phases/e49_shared_sql_infrastructure.md).

**Next:** E13 — Marketplace & GA (0/4, not started), or **E51 — QuotaStore
on PostgreSQL & Concurrency** (0/4, now unblocked — E49 and E50-S1 are both
done) as the next step in the PostgreSQL Production
Completeness program. Beyond GA, the planned v2.1 (E20-E25), v2.2
(E26-E31) and v2.3 (E36-E40) waves are specified but not started.

### Accumulated per-epic record

What follows is the running narrative of what each epic delivered, appended as
the epics landed. It is history, not a statement of the current wave — use the
[Epic status](#epic-status) table below for authoritative per-epic state.

**E0** delivered the foundations
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
a11y, `frontend/e2e/flow-builder.spec.ts`). **E12-S1** (test pyramid & coverage gate)
is now **complete** — unit/integration/e2e suite layout under `backend/tests/`,
deterministic fixtures + `StubLLMProvider`, and an 85% product-code coverage gate
enforced via `make test-backend` / `ci-backend.yml` and a smoke e2e job
(`ci-e2e.yml`); see `docs/testing.md` and
[phases/e12_quality_evals.md](phases/e12_quality_evals.md). **E12-S2**
(extension-point contract tests) and **E12-S3** (agent evals + closed feedback
loop) are now **complete** — a `backend/tests/contract/` tier parametrized over
every `ExtensionPointKind` with a `hostApi` SemVer compatibility check
(`backend/sdk/host_api.py`), and a versioned reference eval
(`evals/reference/agent_smoke/`) runnable via `make eval-reference` /
`autodev eval run` and gated in CI (`ci-evals.yml`), with an integration test
proving eval scores feed the Router/Selector. **E12-S4** (CI Validation Gates)
is now **complete** — `ci-backend.yml` chains a `lint-typecheck` gate (ruff +
mypy) and a `patch-validation` gate (`scripts/validate_patches.py`: dry-run
writes nothing, path-traversal guard rejects escapes) alongside the existing
coverage and security jobs, and `CONTRIBUTING.md` documents the required-check
set enforced as branch protection on `main`
(`scripts/configure_branch_protection.sh`). **Epic E12 is complete (4/4).** The
frontend redesign epics **E15** (done) → **E16** → **E17** (Execution Control Center prototype)
are planned to run before the E11 kickoff; **E15**, **E16**, and **E17** are now
complete — the redesigned Control Center is implemented end to end. **E18** (Control
Center Front Door & Run Experience, also complete) made that UI the platform's front
door: root service descriptor, self-hosted `/docs` under the strict CSP, and
single-command `make run`. A visual-parity audit of the screens against the prototype
(fonts, tokens, spacing, per-screen interaction details, per-screen checklist derived
from ADR-012 and the prototype `shots/`) remains deferred as a proposed **E19**.
**E11 is now complete (4/4) and merged to `main`** (E11-S1/S2/S4 on
2026-08-15, E11-S3 on 2026-08-17): correlated OpenTelemetry traces/metrics/logs
on a self-hosted Collector/Prometheus/Tempo/Loki/Grafana stack (ADR-017);
mandatory OIDC/service-key/session Control Plane RBAC enforced on every route
with durable access/denial auditing (ADR-018); a trusted-only in-process
plugin boundary and a hardened, read-only-root sandbox with a mandatory
Docker network-denial CI gate (ADR-020); a widened HIGH/CRITICAL
secret/vulnerability/license CI gate with an expiring-exception policy; full
settings/backup credential redaction; fail-closed, Alertmanager-alerted
PostgreSQL backups with an executable incident-response runbook; and
**E11-S3 — multi-tenant isolation plus quotas/budgets** (ADR-019): the
authenticated tenant is threaded through every Control Plane route
(including a real cross-tenant leak found and closed in `chat_v2.py`'s
turn endpoints, which had never resolved the principal), a durable
per-tenant quota/budget store and service (`backend/quotas/`) backing
`/v2/quotas` and `autodev quotas get|set`, fail-closed concurrent-run
admission in the Agent Runtime, tenant-budget narrowing plus monthly usage
accounting in the Reasoning Engine, and a Grafana quota dashboard — see
`docs/ops/observability.md`, `docs/security.md`,
`docs/v2_platform/runbooks/e11_incident_response.md`,
`docs/v2_platform/phases/e11_observability_security_multitenant.md`. E11-S4
was implemented in parallel with E11-S2 in a separate worktree since both
depend only on E11-S1. Doc-drift D1 (E11 undercounted while merged work sat
off `main`) is resolved now that the epic → `main` PR has landed.

## Epic status

| Epic | Name | Wave | Status | Stories | Depends on | Doc |
| --- | --- | --- | --- | --- | --- | --- |
| E0 | Foundations & Hardening | Alpha | Done | 7/7 | — | [phases/e0_foundations_hardening.md](phases/e0_foundations_hardening.md) |
| E1 | Plugin Core & SDK | Alpha | Done | 5/5 | E0 | [phases/e1_plugin_core_sdk.md](phases/e1_plugin_core_sdk.md) |
| E2 | Agent Framework | Alpha | Done | 6/6 | E0, E1; E2-S6: E2-S1–S4 | [phases/e2_agent_framework.md](phases/e2_agent_framework.md) |
| E3 | Orchestration Engine | Alpha/Beta | Done | 6/6 | E0, E2 | [phases/e3_orchestration_engine.md](phases/e3_orchestration_engine.md) |
| E4 | Reasoning | Beta | Done | 4/4 | E1, E2 | [phases/e4_reasoning.md](phases/e4_reasoning.md) |
| E5 | Routing / Selection / Evaluation | Beta | Done | 4/4 | E2, E4 | [phases/e5_routing_selection_evaluation.md](phases/e5_routing_selection_evaluation.md) |
| E6 | Skills v2 | Beta | Done | 5/5 | E1 | [phases/e6_skills_v2.md](phases/e6_skills_v2.md) |
| E7 | Context & RAG | Beta | Done | 4/4 | E1, E2, E8, E5 | [phases/e7_context_rag.md](phases/e7_context_rag.md) |
| E8 | Persistence & Data | Alpha/Beta | Done | 4/4 | E0 | [phases/e8_persistence_data.md](phases/e8_persistence_data.md) |
| E9 | APIs, Events & MCP | Alpha/Beta | Done | 4/4 | E8, E2, E6 | [phases/e9_apis_events_mcp.md](phases/e9_apis_events_mcp.md) |
| E10 | UI/UX & Design System | Beta | Done | 4/4 | E3, E9, E1 | [phases/e10_ui_ux_design_system.md](phases/e10_ui_ux_design_system.md) |
| E11 | Observability, Security & Multi-tenant | Beta | Done | 4/4 | E0, E8, E9-S1, E4 | [phases/e11_observability_security_multitenant.md](phases/e11_observability_security_multitenant.md) |
| E12 | Quality & Evals | Alpha/Beta | Complete | 4/4 | E0, E1-E6, E5 | [phases/e12_quality_evals.md](phases/e12_quality_evals.md) |
| E13 | Marketplace & GA | GA | Not started | 0/4 | E1, E12-S2, E11-S4, E0-E12 | [phases/e13_marketplace_ga.md](phases/e13_marketplace_ga.md) |
| E14 | Real Task Execution & Governed Autonomy | Beta | Done | 7/7 | E2, E3, E9-S1, E11-S4 | [phases/e14_real_execution_governance.md](phases/e14_real_execution_governance.md) |
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
| E32 | Isolated Execution Environment (Beta slice) | Beta | Done | 4/4 | E14, E11-S4; E28 (contracts) | [phases/e32_isolated_execution_beta.md](phases/e32_isolated_execution_beta.md) |
| E33 | Secrets & Credential Governance | Beta | Done | 3/3 | E32, E0-S5, E11-S4 | [phases/e33_secrets_credential_governance.md](phases/e33_secrets_credential_governance.md) |
| E34 | Packaging & Global Install | Beta | Done | 3/3 | E14-S7 (CLI), E32 | [phases/e34_packaging_global_install.md](phases/e34_packaging_global_install.md) |
| E35 | Beta Readiness Gates & Evidence | Beta | Done | 3/3 | E32-E34, E11, E12 | [phases/e35_beta_readiness_gates.md](phases/e35_beta_readiness_gates.md) |
| E36 | SDD Operating Model & Document Authority | v2.3 | Not started | 0/4 | E20-E23 | [phases/e36_sdd_operating_model.md](phases/e36_sdd_operating_model.md) |
| E37 | Harness & Looping Excellence: Context-Independent Agents | v2.3 | Not started | 0/5 | E23, E26, E27, E8, E14, E32 | [phases/e37_harness_looping_context_independence.md](phases/e37_harness_looping_context_independence.md) |
| E38 | SOTA Evidence Matrix & Capability Benchmark | v2.3 | Not started | 0/4 | E12, E20-E23, E27, E28 | [phases/e38_sota_evidence_benchmark.md](phases/e38_sota_evidence_benchmark.md) |
| E39 | Product Modes, Agentic Security & Minimum FinOps | v2.3 | Not started | 0/5 | E11, E14, E23, E27, E30, E32, E33 | [phases/e39_product_security_finops_modes.md](phases/e39_product_security_finops_modes.md) |
| E40 | Architecture Fitness Functions & Local-First Degradation | v2.3 | Not started | 0/4 | E1-E14, E20-E23, E26-E30, E32-E35 | [phases/e40_architecture_fitness_local_first.md](phases/e40_architecture_fitness_local_first.md) |
| E41 | Real Code Generation & Agent-Directed Execution | Beta | Done | 5/5 | E2, E14, E16-S3 | [phases/e41_real_code_generation_execution.md](phases/e41_real_code_generation_execution.md) |
| E42 | Execution Visibility & Chat/Command UX | Beta | Done | 6/6 | E41, E9, E11, E15-E18 | [phases/e42_execution_visibility_chat_ux.md](phases/e42_execution_visibility_chat_ux.md) |
| E43 | Execution Transparency: Terminal Transcript, File Browser & Session Stickiness | Beta | Done | 8/8 | E42, E41-S3, E41-S4, E41-S5 | [phases/e43_execution_transparency_file_browser.md](phases/e43_execution_transparency_file_browser.md) |
| E44 | Persistence Read/Write Efficiency | Beta | Done | 5/5 | E8, E16-S1, E43 | [phases/e44_persistence_efficiency.md](phases/e44_persistence_efficiency.md) |
| E45 | Runtime I/O Efficiency: Job Queue, Event Bus, SSE & Indexing | Beta | Done | 5/5 | E0, E8-S2, E9, E43-S6 | [phases/e45_runtime_io_efficiency.md](phases/e45_runtime_io_efficiency.md) |
| E46 | Execution Failure Classification & Self-Repair Governance | Beta | Done | 3/3 | E14, E32, E41-S5, E43-S1 | [phases/e46_failure_classification_self_repair.md](phases/e46_failure_classification_self_repair.md) |
| E47 | Backend Structural Consolidation | Beta | Done | 5/5 | E2, E2-S6, E8, E44, E46 | [phases/e47_backend_structural_consolidation.md](phases/e47_backend_structural_consolidation.md) |
| E48 | PostgreSQL Runtime with pgvector | Beta | Done | 4/4 | E0-S3, E7-S2, E34-S2 | [phases/e48_postgres_runtime_pgvector.md](phases/e48_postgres_runtime_pgvector.md) |
| E49 | Shared SQL Persistence Infrastructure | Beta | Done | 4/4 | E8, E47-S4 | [phases/e49_shared_sql_infrastructure.md](phases/e49_shared_sql_infrastructure.md) |
| E50 | PostgreSQL Schema, Migrations, Tenancy & RLS | Beta | Done | 4/4 | E48, E49, E8-S1 | [phases/e50_postgres_schema_migrations_rls.md](phases/e50_postgres_schema_migrations_rls.md) |
| E51 | QuotaStore on PostgreSQL & Concurrency | Beta | Not started | 0/4 | E49, E50-S1, E11-S3 | [phases/e51_quotastore_postgres_concurrency.md](phases/e51_quotastore_postgres_concurrency.md) |
| E52 | SecretStore on PostgreSQL | Beta | Not started | 0/3 | E49, E50-S1, E33 | [phases/e52_secretstore_postgres.md](phases/e52_secretstore_postgres.md) |
| E53 | PolicyStore on PostgreSQL | Beta | Not started | 0/3 | E49, E50-S2, E14 | [phases/e53_policystore_postgres.md](phases/e53_policystore_postgres.md) |
| E54 | EnvironmentStore on PostgreSQL | Beta | Not started | 0/3 | E49, E50-S2, E32 | [phases/e54_environmentstore_postgres.md](phases/e54_environmentstore_postgres.md) |
| E55 | Plan Step State on PostgreSQL | Beta | Not started | 0/3 | E49, E50-S3, E16-S2 | [phases/e55_plan_step_state_postgres.md](phases/e55_plan_step_state_postgres.md) |
| E56 | SQLite/PostgreSQL Contract Test Suite | Beta | Not started | 0/3 | E49, E50, E51-E55 | [phases/e56_sqlite_postgres_contract_tests.md](phases/e56_sqlite_postgres_contract_tests.md) |
| E57 | CI & Real PostgreSQL E2E | Beta | Not started | 0/4 | E48, E56, E51-E55 | [phases/e57_ci_postgres_e2e.md](phases/e57_ci_postgres_e2e.md) |
| E58 | SQLite → PostgreSQL Data Migration | Beta | Not started | 0/4 | E50-E55, E57 | [phases/e58_sqlite_to_postgres_migration.md](phases/e58_sqlite_to_postgres_migration.md) |
| E59 | Backup, Restore & Disaster Recovery | Beta | Not started | 0/3 | E8-S4, E55-S3, E57-S4 | [phases/e59_backup_restore_disaster_recovery.md](phases/e59_backup_restore_disaster_recovery.md) |
| E60 | Connection Pooling & PostgreSQL Hardening | Beta | Not started | 0/4 | E51-E55, E57, E11-S1 | [phases/e60_postgres_pooling_hardening.md](phases/e60_postgres_pooling_hardening.md) |

Total: **143/260 stories complete** across 60 epics (E19 is a proposed
visual-parity audit, reserved but not yet planned — see the E18 phase doc).

*(2026-07-17: total recomputed from the per-epic Done column — the previous
"51" predated E15–E18 completion and had drifted; +13 planned stories from
the new E32–E35 Beta-hardening epics; +22 planned stories from the E36–E40
v2.3 Platform Excellence planning wave.)*

*(2026-08-21: +5 planned stories from the new E41 Beta-hardening epic —
found by directly running the platform end to end against a real OpenAI key:
`execute-plan` never calls the patch engine, and even the free-text task
descriptions agents produce are silently replaced by hardcoded fallback
metadata regardless of the real LLM call's outcome. See
`phases/e41_real_code_generation_execution.md`.)*

*(2026-08-21: +18 planned stories from the new E44–E47 Beta-hardening
epics — backend efficiency & simplification, distilled from two
independent external code analyses whose claims were all re-verified
against the current tree; 196 → 214 stories, 43 → 47 epics. See
`phases/e44_persistence_efficiency.md` …
`phases/e47_backend_structural_consolidation.md`.)*

*(2026-08-21: +46 planned stories from the new E48-E60 **PostgreSQL
Production Completeness** program — 214 → 260 stories, 47 → 60 epics. Found
by reading the `prod` code path directly: `backend/config/settings.py:332-336`
requires a PostgreSQL `DATABASE_URL`, while `QuotaStore`, `SecretStore`,
`PolicyStore`, and `EnvironmentStore` each raise `ValueError` on exactly that
URL and `StepApprovalStore` silently diverts to `./autodev_plan_step_state.db`
— so four subsystems cannot be constructed at all in a valid production
configuration. Program document:
`docs/v2_platform/postgres_production_completeness.md`.)*

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

Evidence was attached to every criterion on **2026-08-17** (branch
`epic/gap-closure-alpha`). Before that pass only the coverage box was ticked,
even though all Alpha anchor epics had been Done for weeks — the gate had
simply never been walked. Each box below now names the test that proves it.

- [x] A declarative flow executes an agent-plugin end to end with durable state and
      event-store replay. Evidence:
      `backend/tests/integration/test_alpha_gate_flow_replay.py` — the real
      `autodev/agent-coder` plugin resolved through the E2 Agent Registry, run by
      the E3 Flow Engine on durable SQLite with the Event Store on, then
      `reconstruct_run()` + `replay_run()` asserted deterministic. Previously the
      two halves lived in different tests over different flows, and the
      agent-plugin half (`test_flows_api.py::TestAgentFlowEndToEnd`) passes only
      when earlier tests in its file run first — see the plugin-sandbox defect in
      the ledger below.
- [x] Contract tests green for the E1/E2/E3 extension points. Evidence:
      `backend/tests/contract/` (40 passing) — `test_host_api_compatibility.py`
      and `test_provider_contract.py` (E1), `test_agent_contract.py` (E2),
      `test_flow_contract.py` (E3), with `test_extension_point_coverage.py`
      failing the build if any `ExtensionPointKind` lacks a registration.
      The `PENDING` kinds (TOOL, RETRIEVER, VALIDATION_GATE, UI_PANEL,
      EVENT_HANDLER) are extension points that do not exist yet, none of them
      E1/E2/E3, each with a reviewed rationale in `_harness.py`.
- [x] Local-first mode (SQLite + stub provider) runs with no external dependencies.
      Evidence: `backend/tests/integration/test_local_first_mode.py` — clears every
      external-service env var, blocks all non-loopback sockets, then asserts the
      defaults resolve to SQLite + stub provider + in-memory bus and that a
      declarative flow completes. A third test proves the egress guard itself
      fires, so a passing run cannot be vacuous. This replaces the previous
      indirect argument that "the suite happens to pass offline".
- [x] Core coverage >= 85%. ("Core" = `backend/` excluding `backend/tests/*`;
      enforced via `make test-backend` / `ci-backend.yml`
      (`--cov=backend --cov-fail-under=85`, `backend/tests/*` omitted via the
      root `.coveragerc`), product
      coverage measured at 88.29% — E12-S1-T2.)
- [x] Basic per-step traces emitted. Evidence:
      `backend/tests/unit/observability/test_observability.py::test_orchestrator_agent_step_emits_correlated_span`
      — an orchestrator run emits `autodev.run.step.*` spans correlated by
      `autodev.run_id`. `trace_run_step` is wired at all three step boundaries:
      `backend/flows/activation.py`, `backend/agents/runtime.py`,
      `backend/orchestrator/service.py`.

**Wave status.** All five criteria now hold, so **v2.0-alpha is met**. Two
qualifications a reader should carry forward: the plugin-sandbox defect below
means the agent-plugin path is proven under a running server's conditions, not
from a cold process; and E12-S2's extension-point coverage is complete only for
the extension points that exist today.

### v2.0-beta — "full platform in controlled production"

Goal: complete intelligence, context, data, API, UI, security, and quality
capabilities for real, controlled operation. Anchor epics: **E4**, **E5**, **E6**,
**E7**, **E8-S3/E8-S4**, **E9-S2/S3/S4**, **E10**, **E11**, **E12-S2/S3/S4**,
**E14** (real task execution, permission/approval policy, governed sandbox
runners, Web UX + interactive shell for approval, `autodev` CLI install),
**E15/E16/E17** (frontend redesign), **E32** (isolated execution
environment), **E33** (secrets & credential governance), **E34**
(packaging & global install), **E35** (this gate itself — evidence map,
acceptance flow, decisions/risk register, runbooks).

Full evidence map (fact vs. recommendation, per E35-S1):
`docs/v2_platform/beta_gap_analysis.md` §11 — the single source; do not
duplicate its evidence citations here. Originally 12 criteria; criteria 13-15
were added 2026-08-21 by the E48-E60 PostgreSQL Production Completeness
program (`postgres_production_completeness.md`).

- [x] Every extension point has a green contract test and quality gates block merges.
- [x] Design language v2 + Execution Control Center app shell (E15), `/v2` API
      parity (E16), and Control Center screens (E17) are adopted.
- [x] Real task execution runs by default in a fail-closed isolated
      environment with an audited backend/profile decision (E32).
- [x] No secret is ever returned in cleartext by any API/log/event/trace/
      diff/artifact; a leak fixture is detected and audited (E33).
- [x] A clean-environment install is documented and verified; an upgrade
      between two versions preserves data under the schema compatibility
      check (E34).
- [~] The real plan -> code -> apply patch -> validate in sandbox -> evaluate flow runs
      with RBAC, fail-closed budgets, and end-to-end traces — every component
      individually evidenced; no single composed rehearsal until
      `docs/v2_platform/beta_acceptance_flow.md` (E35-S2). **E41 (2026-08-21)**
      closed a gap this criterion's own composed steps depended on: "code" and
      "apply patch" now carry a real LLM-generated file, not simulated/fallback
      content — `backend/tests/unit/orchestrator/test_execution_plan.py` and
      `test_self_repair.py` assert real bytes land on disk through the E0 patch
      engine and that a failing validation command triggers one bounded repair.
      Still `[~]`, not `[x]`: the "no single composed rehearsal" gap E35-S2
      named is unchanged by E41 — this only makes the steps it would compose
      real rather than fake.
- [~] UI is WCAG 2.2 AA on key screens; flow editor round-trips — round-trip
      met; WCAG is component-level (Storybook-axe) only, no consolidated
      per-screen audit.
- [ ] Hybrid retrieval reaches p95 < 300 ms and the recall baseline — harness
      exists (`scripts/benchmark_retrieval.py`); no run against a live
      environment recorded. Open (`phases/e7_context_rag.md`).
- [ ] Run streaming starts < 1 s — functional correctness tested; no
      numeric latency assertion exists. Open.
- [ ] Backup/restore validated (RPO <= 5 min, RTO <= 30 min) in staging — no
      staging environment exists; validated via documented execution
      procedure only. Open (`phases/e8_persistence_data.md`).
- [x] The `prod` profile boots from empty on PostgreSQL 16 + pgvector and
      serves a real vector query — resolved by E48 (`pgvector/pgvector:0.8.3-pg16`,
      extension provisioning split from migration 4, preflight checks).
      Verified 2026-08-22 against a real from-scratch bring-up: all 8
      migrations apply, HNSW index valid, ordered vector query results.
- [ ] SQLite and PostgreSQL pass the same functional contract — 13 tables have
      no PostgreSQL migration and 5 stores refuse a PostgreSQL URL. Open
      (E49-E56).
- [ ] Every pull request runs a real `prod`-profile E2E — no workflow in
      `.github/workflows/` has a `services:` block; all PostgreSQL paths are
      exercised against a monkeypatched `psycopg`. Open (E57).

`[~]` = partially met (real evidence, criterion not fully satisfied). The
first three `[ ]` gaps (retrieval benchmark, streaming latency, staging
restore) need a live environment E35 does not own. The final three were added
2026-08-21 by the E48-E60 PostgreSQL Production Completeness program
(`postgres_production_completeness.md`) — they are named gaps against
verified code evidence, not presumed resolved.

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

- **2026-08-26** — **E50 — PostgreSQL Schema, Migrations, Tenancy & RLS
  complete (4/4)**. Thirteen tables (quotas, secrets, execution policy,
  execution environments, plan step state) previously existed only as
  ad hoc `CREATE TABLE IF NOT EXISTS` calls inside each store's SQLite
  `_create_schema`, none registered in `POSTGRES_STORE_MIGRATIONS`, none
  tracked by `schema_version`, none RLS-protected. **E50-S1**: migration 8
  creates `tenant_quota_policies`, `tenant_usage_windows`, `run_leases`,
  `storage_reservations`, `request_rate_buckets`, and `secrets` on
  PostgreSQL with `JSONB`/`TIMESTAMPTZ`/`BIGINT` types and tenant-first
  keys/indexes. **E50-S2**: migration 9 creates
  `execution_policy_rules`, `execution_dynamic_permissions`,
  `execution_policy_decisions`, `pending_action_decisions`,
  `execution_environments`, and `execution_environment_decisions`, with
  tenant-first indexes serving the pending-decision lookup and
  expiry-scan queries these stores actually run. **E50-S3**: migration 10
  creates `plan_step_state` on PostgreSQL for the first time (`tenant_id`
  plus a foreign key to `plan_documents.session_id`) and gives the SQLite
  table the same `tenant_id` column — pre-migration rows backfill to
  `DEFAULT_TENANT_ID` via SQLite's `ALTER TABLE ... ADD COLUMN ... DEFAULT`
  semantics, no separate `UPDATE` needed. **E50-S4**: migration 11 applies
  `ENABLE`/`FORCE ROW LEVEL SECURITY` plus a `<t>_tenant_isolation` policy
  to all thirteen tables via a new shared `_apply_tenant_rls()` generator
  (`backend/persistence/migrations/postgres_versions.py`), reused instead
  of duplicating the policy SQL per table; `backend/quotas/migrations.py`'s
  `--check` verifier now covers all thirteen on PostgreSQL via
  `_postgres_expected_tables()`, without over-reporting a false gap for
  the twelve that remain SQLite-unchanged by design. Existing migrations
  1-7 were never edited or reordered. Every table's *store* still only
  reads/writes SQLite — the schema exists and is tenant-isolated ahead of
  the store ports (E51-E55), matching how the core tables' RLS was
  originally retrofitted one migration after their creation. Live
  cross-tenant RLS enforcement against a running PostgreSQL is deferred to
  E57 (CI & Real PostgreSQL E2E, not yet started); this epic's tests
  assert migration DDL shape via the `FakeConnection` pattern already used
  by every other PostgreSQL migration test in this codebase.

- **2026-08-23** — **E49 — Shared SQL Persistence Infrastructure complete
  (4/4, ADR-025 Accepted)**. Eight stores (flows, events, artifacts, auth,
  plugins, repository indexing) each duplicated the same small pattern —
  an `_is_postgres` property, `{p}`-template placeholder substitution (or,
  in `registry.py`/`PluginStore`/`VersionedExtensionRegistryCore`, two full
  dual-branch SQL statements), and a `BEGIN IMMEDIATE`-on-SQLite guard.
  **E49-S1**: `backend/persistence/contract.py` is the single
  implementation — `is_postgres`/`placeholder`/`sql`/`jsonb_cast`/
  `json_column_type`/`timestamp_column_type`/`get_connection`/
  `PersistenceIntegrityError`. **E49-S2**: `begin_write`/`for_update_clause`
  give the two dual-branch stores a shared serialization primitive;
  `backend/quotas/store.py`'s docstring no longer claims a `SELECT ... FOR
  UPDATE` PostgreSQL path that doesn't exist (confirmed:
  `grep -rn "FOR UPDATE" backend/` was zero hits before this epic) — it now
  points at the primitive E51 will use to implement that port. Verified
  with a real 4-thread SQLite race (loses updates without `begin_write()`,
  never with it) and, live, the same race against real PostgreSQL via
  `for_update_clause()`. **E49-S3**: all eight stores migrated onto the
  contract; `registry.py`/`PluginStore`/`VersionedExtensionRegistryCore`
  collapsed their `%s::jsonb`-vs-`?` dual-branch statements into single
  `{p}{jsonb}`-templated ones (unconditional lowercase `excluded`, already
  proven dialect-safe elsewhere). Connection lifecycle (per-call,
  per-thread-cached, context-manager, per-batch — genuinely different
  across the eight) was deliberately left untouched. Zero test files
  edited; the combined regression run (430 tests) passes unmodified.
  **E49-S4**: `backend/tests/unit/persistence/test_boundary_guard.py`
  AST-scans `backend/` for direct `sqlite3.connect(`/`psycopg.connect(`
  outside `backend/persistence/`, against an explicit, story-annotated
  allowlist (the five category-3 stores → E51-E55, plus
  `backend/ops/doctor.py`'s preflight check and the read-only tenancy
  verifier, both permanent) with a second test asserting no entry goes
  stale. Demonstrated live: the guard fails on a deliberately added
  `sqlite3.connect()` and passes once removed.

- **2026-08-22** — **E48 — PostgreSQL Runtime with pgvector complete (4/4,
  ADR-024 Accepted)**, the first epic of the PostgreSQL Production
  Completeness program. **E48-S1**: the `prod`/`postgres` Compose profiles
  now ship `pgvector/pgvector:0.8.3-pg16` (`infrastructure/docker-compose.yml`)
  in place of stock `postgres:16-alpine`; the version pair (PostgreSQL 16 /
  pgvector 0.8.3) is pinned and documented, not a floating tag. **E48-S2**:
  `CREATE EXTENSION IF NOT EXISTS vector` moved out of migration 4
  (`_pg_m4_create_code_embeddings_table`) into a new, idempotent
  `provision_vector_extension()` (`backend/persistence/postgres_adapter/vector_provisioning.py`)
  run before the migration runner on every `PostgresStore` construction; it
  detects an already-installed extension via `pg_extension` and proceeds
  without `CREATE EXTENSION` privilege, or raises `VectorExtensionUnavailable`
  with an actionable operator message when absent and not creatable.
  Migration numbering and the `code_embeddings` RLS policy are unchanged.
  **E48-S3**: `backend/ops/doctor.py` gained four ordered checks
  (`postgres_server_version`, `pgvector_extension_present`,
  `pgvector_extension_usable`, `pgvector_hnsw_index`), appended only for a
  `postgresql://` `DATABASE_URL` and skipped if connectivity already failed;
  each reports its own distinct, actionable cause (the readiness connection
  uses autocommit so one failing check cannot poison the next one's
  transaction). `backend/ops/bootstrap.py` needed no change — it already
  gates store construction on `diagnostics_ok()`. A new `GET /readiness`
  endpoint surfaces the same checks for an orchestrator; `/health` is
  unchanged. **E48-S4**: extension install/upgrade/rollback and the
  supported version pair are documented in `docs/config.md`;
  `docs/feature_matrix.md`'s pgvector row no longer describes the runtime as
  unable to satisfy its own migration. Verified end-to-end against a real,
  from-scratch `pgvector/pgvector:0.8.3-pg16` bring-up: all 9 preflight
  checks pass, all 8 PostgreSQL migrations apply (`schema_version=8`), the
  HNSW index is valid, RLS is enabled and forced, and a real cosine-distance
  vector query returns ordered results; a deliberately unprovisioned
  database fails `pgvector_extension_present`/`_usable`/`pgvector_hnsw_index`
  independently with distinct messages. No `/v2` contract changes.

- **2026-08-21** — **Planning-only: added the E48-E60 PostgreSQL Production
  Completeness program — 13 Beta-hardening epics, 46 planned stories**, on
  `main` (same posture as the E44-E47 planning entry below: documents only, no
  code, schema, or migration changed, nothing pushed). Program document:
  `docs/v2_platform/postgres_production_completeness.md`. **Origin:** reading
  the `prod` code path directly rather than the tracker.
  `backend/config/settings.py:332-336` requires a `postgresql://`
  `DATABASE_URL` in the `prod` profile, while `QuotaStore`
  (`backend/quotas/store.py:49`), `SecretStore`
  (`backend/secret_store/store.py:48`), `PolicyStore`
  (`backend/execution/policy.py:206`), and `EnvironmentStore`
  (`backend/environments/store.py:38`) each raise `ValueError` on exactly that
  URL — so quotas, secrets, execution policy, and execution environments
  **cannot be constructed at all** in a valid production configuration, and
  `StepApprovalStore` (`backend/plans/step_state.py:132`) silently diverts
  plan-step approval state to `./autodev_plan_step_state.db`, a file no
  replica shares and no backup manifest covers. Three further verified
  defects: `postgres_versions.py:253` runs `CREATE EXTENSION IF NOT EXISTS
  vector` against `infrastructure/docker-compose.yml:116`'s stock
  `postgres:16-alpine`, so PG migration 4 cannot succeed on the shipped
  stack; all 13 domain tables are created by `CREATE TABLE IF NOT EXISTS`
  outside `MigrationRunner`, so none is in `schema_version` and none has RLS;
  and no workflow in `.github/workflows/` has a `services:` block, so every
  PostgreSQL path — both adapter packages, all 7 migrations, RLS, pgvector —
  is exercised only against a monkeypatched `sys.modules["psycopg"]`. That
  last one is the root cause: the divergence persisted because nothing ever
  asked a store to behave identically on both backends. **Epics:** E48
  runtime + pgvector (4), E49 shared SQL persistence contract (4), E50 schema,
  migrations, tenancy and RLS for the 13 tables (4), E51-E55 the five store
  ports with their own concurrency invariants (4/3/3/3/3), E56 the
  SQLite/PostgreSQL contract suite (3), E57 real PostgreSQL in CI plus a
  `prod` E2E (4), E58 `autodev database migrate` (4), E59 backup/restore/DR
  (3), E60 pooling and hardening (4, sequenced last so it optimizes a system
  that works). **New ADRs**, all `Proposed`, each decided inside its owning
  epic: ADR-024 (pgvector runtime image and extension provisioning, E48),
  ADR-025 (SQL persistence boundary, dialect scope, no ORM — extending
  E47-S4's recorded stance, E49), ADR-026 (one-way SQLite → PostgreSQL
  migration and cutover, no permanent dual-write, E58). Also backfilled the
  missing **ADR-023** row in `decisions/README.md`, which existed on disk but
  not in the index. **Gate impact:** three criteria added to §18.9 v2.0-beta
  (13-15), all `[ ]` Open — Beta cannot be signed off while four subsystems
  cannot start in `prod`. Existing decisions this program implements rather
  than revisits: ADR-001, ADR-010, ADR-011, ADR-013, ADR-014, ADR-019,
  ADR-022.

- **2026-08-21** — **E47 — Backend Structural Consolidation complete (5/5)**,
  the last of the four Beta-hardening backend-efficiency epics, sequenced
  after E44/E46 so structure was extracted from the post-fix shape rather
  than refactored twice. No public `/v2` contract changes; internal
  consolidation only, verified by the full backend suite (2,018 tests)
  after each story and once more at epic completion. **E47-S1**: the
  `GET /agents` catalog (imports, instantiation, `metadata_model()`
  introspection for all 11 default + specialized agents) is now built once
  behind a lock and cached, instead of rebuilt on every request; the
  `/v2/extensions` agent enable/disable toggle invalidates the cache so
  changes are reflected without a restart. **E47-S2**: `llm/gateway.py`'s
  `complete()` and `_stream_prepared()` shared attempt machinery — target
  iteration, capability-error recording, call/token budget checks, attempt
  numbering, the retry/fallback/fail decision — is now one
  `_AttemptCoordinator`, with parity tests pinning identical attempt
  sequences across both paths; a new optional `RetryBackoff` (exponential +
  jitter, defaulting to zero delay) is available between same-target
  retries. **E47-S3**: `AgentRegistry` and `SkillRegistry`'s 15 duplicated
  methods (schema creation, upsert, resolve/list, deprecate/activate +
  plugin-event emission, catalog rendering, plugin-store sync, SemVer
  matching) now share one `VersionedExtensionRegistryCore`
  (`backend/plugins/registry_core.py`) by composition; each registry keeps
  only its own manifest-format specifics (`find_by_capability`/agent
  loading vs. `find_by_trigger`/YAML loading). **E47-S4**: `sqlite_adapter.py`
  (942 ln) and `postgres_adapter.py` (1013 ln) — both over the 500-line
  guideline — split into packages by data domain (sessions/runs/messages/
  eval_scoring mixins + store/plan_store), with shared pure codecs
  (`backend/persistence/codecs.py`: JSON encode/decode, timestamp handling,
  run/session/step/promotion record shaping, step-batch preparation)
  factored out; SQL text (placeholders, upsert dialect, RLS) stays
  per-backend as planned — no ORM, no generic adapter. **E47-S5**:
  `orchestrator/service.py` (2,401 ln, one class doing everything) became
  `backend/orchestrator/service/`, split into mixins by concern (chat,
  queries, plan_lifecycle, task_dispatch, self_repair, graph) composed by
  `core.OrchestratorService`, each module under 420 lines: the E32
  execution-environment provision/bind/collect/teardown lifecycle is now
  its own `ExecutionEnvironmentScope`; `_process_tasks`'
  results/steps/history triple-append (previously built inline at two
  separate call sites) is centralized behind one typed
  `TaskAppendEntry`/`append_task_entry`; `_build_execution_tasks`'s nine
  near-identical inline loops became one small builder per artifact
  section, composed by explicit chaining; session/run summary building and
  the background message-run job pathway moved into their own modules.
  Public import surface (`backend.orchestrator.service.*`) is unchanged.

- **2026-08-21** — **E46 — Execution Failure Classification & Self-Repair
  Governance complete (3/3, ADR-023)**. Self-repair no longer spends a
  Coder call on a failure it cannot fix. **E46-S1**: `ExecutionFailureKind`
  (`code_failure`/`command_not_allowed`/`policy_denied`/
  `environment_unavailable`/`dependency_missing`/`timeout`/
  `internal_error`) is set at the origin — the sandbox runner's
  allowlist/workspace-containment checks, `CompositeActionRunner`'s
  environment-policy denial, `TaskExecutor`'s execution-policy denial and
  `deny_all` (human decision or environment-provisioning failure) — never
  inferred from `stderr` afterwards. `ExecutionResult` carries the new
  additive `failure_kind` plus a derived `repairable_by_code_change`
  property; `execution.action.failed` gains an additive `failureKind`
  field. **E46-S2**: `_maybe_self_repair` now skips the Coder entirely —
  emitting the new `execution.repair.skipped` event and recording
  `self_check="skipped_non_repairable"` — when every failed result is
  classified and none is repairable by a code change; a result with no
  `failure_kind` (pre-E46 producers) still fails the gate open to the old
  reflex. **E46-S3**: `_process_tasks` now dispatches the whole batch
  first, then runs one batched repair pass
  (`_maybe_batch_self_repair`) over every failing validation task instead
  of one `_maybe_self_repair` call per task — multiple failing validations
  converge on exactly one Coder call carrying every repairable failure's
  evidence, one combined write, and only the tasks that were actually
  repaired are re-validated afterwards. This closes the exact blast radius
  E42/E43's live run demonstrated (10/10 validation tasks failing on a
  sandbox policy rejection triggered 10 wasted repair attempts) and E43-S1
  only patched one instance of.

- **2026-08-21** — **E44 — Persistence Read/Write Efficiency complete
  (5/5)**. Every defect the epic was written against is closed, and each
  is pinned by a cost-regression test rather than an observation.
  **E44-S1**: `RunRepository` gains `get_run(run_id, tenant_id)` on both
  adapters (indexed primary-key read plus one batched step query, one
  connection); `chat_v2._find_turn_by_id` is now that single call, so
  `GET /v2/turns/{id}` costs 2 statements instead of `1 + 3S + R`.
  `_decode_run` became pure in both adapters, which also removed the
  per-run `list_run_steps` N+1 — `list_runs` is 2 statements for any
  number of runs. **E44-S2**: Postgres batches step and message inserts
  with `executemany` (SQLite already did), so a checkpoint is one round
  trip. **E44-S3**: new `list_sessions_page`/`list_runs_page` protocol
  methods paginate in SQL (`LIMIT`/`OFFSET` + `COUNT`), and session pages
  derive `message_count`/`last_activity` from one aggregate over the page
  instead of replaying every session's history — `/v2/sessions`,
  `.../runs` and `.../turns` are a fixed 3 statements per page.
  `SessionV2` gains `message_count`/`last_activity` and listings no longer
  embed `history` (the detail endpoint still does; no v2 frontend consumer
  read it from the listing). **E44-S4**: `append_messages` now takes only
  the new tail and allocates sequences from `MAX(sequence) + 1` inside the
  insert transaction — one row read per append instead of the whole
  conversation — with a new unique `(tenant_id, session_id, sequence)`
  index so concurrent appends fail closed. **E44-S5**: `run_steps` gains a
  `position` key (backfilled from insertion order) with a unique
  `(run_id, position)` index; checkpoints trim only surplus rows and
  upsert the rest, suppressing the update when a row is unchanged, so the
  Nth checkpoint writes one row and a run writes O(N) instead of O(N²).
  The full-replace path survives, clearly named, as
  `replace_run_steps_for_import`. Explicit non-goals held: no ORM, no
  generic SQL abstraction, no caching layer, no event-store changes.
  One pre-existing defect was fixed on the way: `MigrationRunner` takes no
  cross-connection lock, and SQLite has no `ADD COLUMN IF NOT EXISTS`, so
  the check-then-`ALTER` pattern in the `run_type`, `current_state`,
  `tenant_id` and `content` migrations could race two concurrently
  constructed stores into a "duplicate column name" crash (it surfaced
  when E44-S5's own column hit it). `_add_column_if_missing` now
  centralizes the guard.

- **2026-08-21** — **Planning-only: added E44–E47 — backend efficiency &
  simplification (Beta-hardening, 18 planned stories across 4 epics)**.
  Source: two independent external code analyses of the backend (ChatGPT
  and Codex, both asked whether the backend could be simplified, made more
  efficient, and rid of unnecessary loops); both converged on repeated I/O
  and structural duplication rather than algorithmic loops. Every claim
  was re-verified against the current tree (`943845f` + the E43-S8 merge)
  before planning — **all confirmed**, several understated
  (`orchestrator/service.py` is now 2,046 lines; the `GET /v2/turns/{id}`
  lookup compounds three N+1 patterns for `1 + 3S + R` worst-case queries;
  E43-S6 made chat turns the highest-volume job type on a queue that never
  deletes completed records). **E44 — Persistence Read/Write Efficiency**
  (5 stories): `get_run` direct lookup (turn fetch ≤ 2 queries), batched
  step loading (kills the per-run `list_run_steps` N+1 — one fresh
  connection per run today — in both adapters), DB-level pagination for
  session/run listings (currently loaded whole then sliced in memory),
  incremental message append (no full-history reload just to take
  `len(existing)`), and incremental run-step persistence (replaces
  DELETE+reinsert of the whole step list on every `update_run`,
  O(N²) → O(N)). **E45 — Runtime I/O Efficiency** (5 stories): BLPOP
  worker + graceful shutdown (replaces the idle ~10 LPOP/s poll loop),
  job-record TTL/retention with O(1) `stats()`, event-bus unsubscribe +
  SSE `finally` cleanup (today every connect permanently leaks a
  subscriber — acknowledged in-code), non-blocking replay (sync `XRANGE`
  currently runs on the event loop) + `XADD MAXLEN` retention, and
  indexing traversal pruning (today `rglob` descends into
  `.git`/`.venv`/`node_modules` and persists one statement per chunk) +
  batched writes. **E46 — Execution Failure Classification & Self-Repair
  Governance** (3 stories, ADR-023): typed `failure_kind` on
  `ExecutionResult` set at the failure origin, self-repair gated to
  `code_failure` only — today a sandbox policy rejection triggers a Coder
  LLM repair of potentially-correct code, the exact failure mode E42's
  live run demonstrated at 10/10 validation tasks and E43-S1 fixed only
  one instance of — plus an at-most-one-repair-per-batch policy. **E47 —
  Backend Structural Consolidation** (5 stories, sequenced last so
  structure is extracted from the post-E44/E46 shape): agent-catalog
  cache (no per-request dynamic imports on `GET /agents`), shared LLM
  gateway attempt coordinator (retry/fallback/telemetry machine currently
  duplicated across `complete()`/`_stream_prepared()`, no backoff),
  Agent/Skill registry unification (15 structurally identical methods),
  shared persistence codecs + adapter split under the 500-line guideline
  (closes this tracker's long-standing `postgres_adapter.py` follow-up),
  and OrchestratorService decomposition. Both analyses' "these loops are
  healthy, do not touch" verdicts (FlowEngine `_run_loop`, `map_handler`
  budgeted scheduler, graph-validation DFS) are recorded as explicit
  non-goals in the phase docs. Same pattern as E32-E35/E41-E43: extends
  the Beta wave before sign-off. See `phases/e44_persistence_efficiency.md`,
  `phases/e45_runtime_io_efficiency.md`,
  `phases/e46_failure_classification_self_repair.md`,
  `phases/e47_backend_structural_consolidation.md`. No stories started.
- **2026-08-21** — **E43-S8 added and completed: Chat auto-executes its
  derived plan, live, in the same run.** The user's real ask after testing
  S6/S7: a Chat message only ever drove the conversational agent pipeline —
  real file writes/commands still required a second, manual "Run plan"
  click. New fail-closed flag `autodev_chat_auto_execute` (env
  `AUTODEV_CHAT_AUTO_EXECUTE`, default off); when on, `_run_message_job`
  chains `build_execution_plan` + the same `_process_tasks`/
  `_finalize_plan_run` calls "Run plan" already uses onto the *same*
  run_id, so `getTurnV2` polling and `RunTimelinePanel`'s live subscription
  need no new plumbing. "Run plan" is unchanged and stays available either
  way. Found and fixed a genuine race while stress-testing: an interim
  "reopen the run as RUNNING" call between the conversation's own
  completion write and the chained dispatch still left a narrow window
  where a poller could observe a premature "completed" and stop watching.
  Root-caused by giving `_execute_message_run` a `finalize: bool = True`
  parameter — callers chaining more work pass `finalize=False` so the run
  row is never prematurely marked complete at all. See
  `phases/e43_execution_transparency_file_browser.md`'s E43-S8.
- **2026-08-21** — **E43-S7 added and completed: live `run.timeline.*`
  events during Chat turns.** Found via the user's live testing of E43-S6:
  even with async turn creation, the Execution panel stayed on "Waiting"
  the whole turn. Distinct root cause from S6: `run.timeline.*` events were
  only ever emitted by the "Run plan" task-dispatch pipeline
  (`_process_tasks`) — the Chat turn's own agent graph
  (`_execute_message_run`'s `self._graph.invoke(...)`) never emitted them,
  a pre-existing gap predating this epic. `_make_agent_node`'s node
  function now emits one `run.timeline.*` event per completed mapped agent
  (navigator/analyzer → analysis, coder → patch, validator → validation),
  reusing `_process_tasks`'s exact event type/schema/mapping — no new event
  type, no frontend change needed (`RunTimelinePanel` already renders
  whatever arrives). See `phases/e43_execution_transparency_file_browser.md`'s
  E43-S7.
- **2026-08-21** — **E43-S6 added and completed: asynchronous turn
  creation.** Found via the user's own manual verification of E43-S1..S5 in
  the actual product UI: sending a Chat message showed "Sending..."
  indefinitely, the composer never cleared, and the Execution panel showed
  nothing until navigating away (to Sessions) and back forced a fresh
  re-fetch. Root cause: `POST /v2/sessions/{id}/turns` ran the entire
  7-agent pipeline synchronously in one HTTP request
  (`OrchestratorService.handle_message` → `self._graph.invoke(...)`), so
  the frontend never had a `run_id` early enough to open its live event
  stream against — not a gap in E43-S2/S3's rendering, which is correct.
  Added `OrchestratorService.begin_message`: admits the run synchronously
  (lease, initial `RunStatus.RUNNING` row, the `flow.run.started` event
  that creates the run's `EventStore` projection) then runs the graph in a
  background job via the existing `backend.jobs.queue` infrastructure
  (reused as-is, same "handler registered in the enqueuing module" pattern
  `backend/repository/indexing.py` already established) — no new
  subsystem. Added `RunStatus.FAILED` (previously a graph exception left
  the run stuck at `running` forever, silent once there's no HTTP caller
  left to surface a 500 to). `handle_message` itself, and its three other
  callers (CLI, frozen v1 `/chat`, `orchestration.py`), are unchanged.
  Also fixed, discovered while testing: `backend/cli_shell.py`'s
  `run_goal` assumed synchronous turn completion the same way and started
  400ing (executing a plan before the now-backgrounded pipeline had
  produced any artifacts) — added `ShellSession.wait_for_turn`. See
  `phases/e43_execution_transparency_file_browser.md`'s E43-S6 for full
  detail; automated coverage in
  `backend/tests/unit/orchestrator/test_begin_message.py`.
- **2026-08-21** — **E43 — Execution Transparency: Terminal Transcript,
  File Browser & Session Stickiness is complete (5/5)**, on
  `epic/e43-execution-transparency-file-browser`. **E43-S1** root-caused
  the sandbox `cd` failure precisely: `executor.derive_actions` tokenizes
  an agent-declared `"cd <dir> && <cmd>"` string with plain `.split()`, so
  `SandboxRunner` saw `command[0] == "cd"` and rejected it before the real
  command was ever inspected; the runner now folds a leading `cd`-prefix
  into `cwd`/`command` before the allowlist/workspace checks run, reusing
  `apply_patch`'s containment guard. **E43-S2** found the "Chat Execution
  panel" the epic doc describes is `ExecutionConsolePanel.tsx`, whose
  `output` field was the task's static pre-execution `description` —
  never the real result — because `ExecutionResult` never carried the
  command/path that actually ran; extended `ExecutionResult` and the
  `execution.action.*` event schema with `command`/`path`/`stdout`/
  `stderr` (a deliberate, backward-compatible event-payload extension per
  the epic's own contract note, not a new backend surface) and built one
  shared `frontend/lib/transcript.ts` formatter both the Live-stream tab
  and the Chat panel now render through. **E43-S3** added a `step_label`
  to `ExecutionAction` ("Creating `<file>`" for writes, the task's own
  title for commands), threaded through the same events. **E43-S4** added
  `GET /v2/repository/tree`/`file` (new `repository:read` scope) plus a
  lazily-expanding file-tree panel and read-only viewer at a new `/files`
  route — confirmed the platform has one project root per deployment, not
  one per session, so there is no session-scoped tree to look up.
  **E43-S5** fixed Patches (previously defaulted to the first session in
  the list) and made visiting a session's detail page set the app-wide
  active session too, generalizing E42-S3 beyond Plans/Execution.
  Automated regression tests added per story; full backend and frontend
  unit suites pass. **Not performed:** the DoD's full live Chat → Run plan
  rehearsal and interactive browser click-through (no headless Chrome
  available in the execution environment) — S4's endpoints were confirmed
  live via `curl` against a throwaway backend instead. Given E42-S5's own
  claimed completion turned out not to match what shipped, a real manual
  pass in the product UI is recommended before treating this epic as
  unconditionally signed off. See
  `phases/e43_execution_transparency_file_browser.md`.
- **2026-08-21** — **Planning-only: added E43 — Execution Transparency:
  Terminal Transcript, File Browser & Session Stickiness (Beta-hardening,
  5 planned stories)**. Found by re-testing the now-Done E42 in the actual
  product UI: E42-S1's event stream is genuinely real (confirmed live SSE
  events for a Chat-triggered run), but E42-S5 rendered it as raw JSON
  payloads instead of a readable command/output view — the story's DoD
  ("live command output") was satisfied by "live events," not by anything
  a user would recognize as terminal output. A second, more severe defect
  was confirmed from a full run transcript, not just inferred: tasks 1-36
  (planning/analysis/architecture/implementation/operations) all
  `Completed`, then **every one** of tasks 37-46 — the entire validation
  phase, 10/10 tasks, each a different command — `Failed`, all with
  "Command 'cd' is not in the allowed list." The sandbox allowlist
  (`pytest`/`ruff`/`npm`/`python`/`python3`) checks only a command's first
  token; agent-declared commands naturally arrive as `cd <dir> && <real
  command>`, so validation currently **cannot pass at all, for any goal**,
  regardless of generated-code correctness — this is also why E41-S5's
  self-verification retry loop was observed failing
  (`outcome: "failed_after_retry"`) even though the generated code itself
  imports and runs cleanly. Given the severity, this got its own story
  (**E43-S1**, ahead of the rendering work) rather than a footnote on the
  transcript-rendering story. User-specified requirements captured
  verbatim for the rest: the panel should look like a real terminal
  (command + real stdout/stderr), show which command wrote which file,
  carry plain-language step labels ("Creating main.py"), plus two new
  asks — a project file-tree browser with in-app file reading, and every
  page defaulting to the most recently selected session (E42-S3 only
  fixed Plans/Execution; this generalizes it app-wide). Same pattern as
  E32-E35/E41/E42: extends the Beta wave before sign-off. See
  `phases/e43_execution_transparency_file_browser.md`. No stories started.
- **2026-08-21** — **E42 — Execution Visibility & Chat/Command UX is
  complete (6/6)**, on `epic/e42-execution-visibility-chat-ux`. **E42-S1**
  root-caused the 404 precisely: `stream_run_events` gated
  existence/tenant ownership on the Flow Engine's own `flow_runs` table,
  but both the Flow Engine and the Orchestrator already published onto the
  same `EventBus` via `emit_event()` — the stream body already worked for
  both paths, only the gate didn't. Swapped it to
  `EventStore.get_projection(run_id)`, fed by both engines, for one
  engine-agnostic check. **E42-S2** audited every `@requires_scope` under
  `/v2/execution/*` and `/v2/runs/*`: `policy:read`/`policy:admin` were
  used by `execution_policy_v2.py` but never defined in `ROLE_GRANTS` —
  not an `OWNER`-specific gap, a missing scope pair — added to the
  VIEWER/ADMIN tiers respectively. **E42-S3** extended the shell store
  with `activeSessionId`/`activeRunId`, published from Chat, consumed by
  Plans/Execution as their default (manual entry still overrides).
  **E42-S4** reworked `MessageList` into right/left chat bubbles with
  collapsible long turns, and fixed Chat's specific nested-scroll bug
  (audited Plans/Execution too; they already used the correct pattern).
  **E42-S5** found a gap the epic doc didn't anticipate: the
  `run.timeline.*` event taxonomy (built in E16-S1 to carry live
  stdout/log excerpts, role-mapped in `backend/api/timeline_roles.py`) was
  never actually emitted anywhere — zero non-test call sites in the whole
  backend. `Orchestrator._process_tasks` now emits one `run.timeline.<stage>`
  event per task with its captured `ExecutionResult.stdout`/`.stderr`; the
  frontend consumer (`useRunTimeline` → `ExecutionTimeline`) was already
  fully built and wired into Chat's execution panel, it only needed real
  events — the one frontend gap (`applyTimelineEvent` overwriting instead
  of accumulating a stage's output across multiple same-stage tasks) was
  also closed. **E42-S6** gave the flow editor's canvas column the same
  `lg:min-h-0` large-viewport growth its sibling palette column already
  had, instead of a permanent `min-h-[420px]` cap. `make check`: exit 0
  (backend lint+typecheck+tests, frontend lint+typecheck+test+build,
  compose config all clean). Not merged to `main`; no push/PR without
  explicit authorization.
- **2026-08-21** — **Planning-only: added E42 — Execution Visibility &
  Chat/Command UX (Beta-hardening, 6 planned stories)**. Found by running
  the now-fixed E41 pipeline through the actual product UI (backend +
  frontend) against a real OpenAI key: a "Build a simple payment API" goal
  run via Chat's Run plan button correctly wrote a complete, working
  project (verified: all 4 generated tests pass) — but the UI meant to show
  that happening has real defects. Three root-caused: (1)
  `GET /v2/runs/{run_id}/events/stream` 404s for every Chat-triggered run
  because it resolves `run_id` against the Flow Engine's run store, not the
  Orchestrator's — the two execution paths were never unified under one
  event stream; (2) `GET /v2/execution/policy/dynamic` 403s under the local
  zero-config `Role.OWNER` principal — a real scope gap, not a routing
  issue; (3) the Plans page never defaults to the active session, requiring
  manual session-ID entry. Plus three UX asks: real chat-bubble layout with
  collapsible turns, a live command stdout/stderr panel, and more usable
  space in the flow editor canvas. Same pattern as E32-E35 and E41: extends
  the Beta wave before sign-off. See
  `phases/e42_execution_visibility_chat_ux.md`. No stories started.
- **2026-08-21** — **E41 — Real Code Generation & Agent-Directed Execution
  is complete (5/5)**, on `epic/e41-real-code-generation-execution`
  (branched from `main` after PR #113 merged its own planning-only docs
  commit). Closes the gap this epic itself found: **E41-S1** fixed one bug
  confirmed in 11 `LangChainAgent` subclasses (`build_metadata()` always
  discarding a successful LLM call's real output for `fallback_result()`'s
  hardcoded metadata) in one place (`backend/agents/base.py`) — binds the
  model directly to `metadata_model()` via LangChain's
  `with_structured_output()`, falling back to best-effort text parsing only
  when the provider doesn't support it. **E41-S2** gave `CoderOutput` an
  additive `files: list[{path, content}]` field (bounded to 20 files / 64KB
  each), with `CoderAgent`'s prompt now asking for real, runnable content.
  **E41-S3** wired `TaskExecutor.derive_actions` to turn coder-provided
  files into `create_file` actions dispatched through the same
  `backend.patches.engine` functions the Patches API already uses — no new
  action type or root-resolution/approval-gating code needed, both already
  existed generically from E14/E32. **E41-S4** gave DevOps/Validator
  agents an additive `commands: list[str]` field; the executor now prefers
  agent-declared commands over keyword-sniffing free text for both
  `operations` (previously derived nothing) and `validation` categories,
  keeping the keyword heuristic as the unchanged stub-provider fallback.
  **E41-S5** closed the loop: `_process_tasks` runs one bounded coder
  repair — scoped to the files the batch already wrote, fed the failing
  command's captured output — when a structured validation command fails,
  re-validates once more, and surfaces the three-way outcome
  (`first_try_pass`/`repaired_then_pass`/`failed_after_retry`) in both the
  task's `AgentExecution.metadata` and a new durable event,
  `execution.verification.outcome` (catalog 51 -> 52). A pending
  human-approval decision on the repair write is treated as a failed
  repair rather than a second nested pause — a documented scope boundary,
  not a silent gap. `make check`: backend 1890 passed/2 skipped, 91.83%
  coverage, ruff+mypy clean; frontend lint/typecheck/vitest (178 tests)
  clean. `next build` did not complete — blocked by a pre-existing,
  root-owned `frontend/.next/` directory from before this epic's work
  (unrelated to any file this epic touched); `check-compose` did not run
  as a result. Not merged to `main`; no push/PR without explicit
  authorization.
- **2026-08-21** — **Planning-only: added E41 — Real Code Generation &
  Agent-Directed Execution (Beta-hardening, 5 planned stories)**. Found by
  directly running the platform end to end against a real OpenAI key on a
  trivial goal: `execute-plan` never calls `backend.patches.engine` at all
  (only the separate, human-driven Patches HTTP API does), and even the
  free-text task descriptions agents are supposed to produce are not real —
  `PlannerAgent.build_metadata()` and the inherited `LangChainAgent`
  default both discard a successful LLM call's real output and always
  return `fallback_result()`'s hardcoded data, verified live (real,
  on-topic GPT content in `AgentResult.content`; identical generic fallback
  text in the stored `artifacts` metadata `execute-plan` actually reads).
  Same pattern as E32–E35: extends the Beta wave before sign-off rather than
  starting new GA/v2.1+ scope, since "the platform can turn a goal into
  working code" is not covered by any of the 12 tracked v2.0-beta exit
  criteria despite being more fundamental than any of them. See
  `phases/e41_real_code_generation_execution.md`. No stories started.
- **2026-08-20** — **Beta-exit documentation rebuild pass executed**
  (`docs/v2_platform/documentation_rebuild.md`, steps 1–6 and 8; step 7 is
  GA-only). Documentation-only: no source file was modified, so no test run
  was required — verified by `git diff` containing exclusively `*.md` paths.
  Four parts:
  **(1) Language.** `docs/architecture/v2_platform_reference.md` (7,807
  lines) was translated pt-BR → English, along with `beta_gap_analysis.md`,
  `e17_pause_handoff.md` and residual fragments elsewhere. The reference
  doc went from 2,893 Portuguese tokens to 0. Structure was verified
  identical after reassembly (1 h1 / 25 h2 / 200 h3 / 60 h4 / 49 h5, 60
  fenced blocks, sections 1–24); all 57 code fences are byte-identical, only
  the 3 embedded markdown templates were translated and were aligned to the
  existing English wording in `templates/`. A second pass translated
  documentation *inside* fences (YAML comments, mermaid labels) across 40
  blocks. 21 in-document TOC anchors that still pointed at pt-BR heading
  slugs were regenerated. The literal Portuguese continuation-command
  triggers in `CLAUDE.md`/`AGENTS.md` were deliberately **not** translated —
  they are strings the user types.
  **(2) Structure.** Ten v1-era documents were relocated to
  `docs/archive/v1/` with standardized banners and a v1 → v2 map
  (`docs/archive/v1/README.md`). This amends the playbook's previous
  banner-only rule; the amendment and its rationale are recorded in
  `documentation_rebuild.md` so the GA pass does not re-litigate it.
  All inbound/outbound links, link labels and prose path mentions were
  rewritten; link check reports 0 unresolved relative links across 168
  tracked Markdown files.
  **(3) Status.** `README.md` (which still claimed "Alpha wave, E0–E2
  complete"), `DESCRIPTION.md`, `CHANGELOG.md`, `docs/roadmap.md`,
  `docs/feature_matrix.md`, `docs/product/project_charter.md`,
  `docs/security*.md`, `docs/testing.md` and
  `docs/implementation/self_hosting_oss.md` were refreshed to describe the
  Beta platform.
  **(4) Release.** `v2.0-beta` published as a GitHub **pre-release**. No
  gate criterion was flipped by this pass: the three `[ ]` items
  (retrieval p95 benchmark, streaming-start latency, staging backup/restore)
  and the two `[~]` partials remain exactly as E35-S1 assessed them, and the
  release notes state them explicitly under *Known limitations*.

- **2026-08-19** — **E35 — Beta Readiness Gates & Evidence is complete
  (3/3)**, on `epic/e35-beta-readiness-gates` (branched from `main` after
  E34 merged via PR #107). **E35-S3** closed the epic: open-decisions
  register, risk register & runbooks. `beta_gap_analysis.md` §7's
  decisions table records ADR-013/014/015 as all **Accepted** — resolved
  within their own epics rather than left open as this story originally
  anticipated, kept traceable with options/recommendation/owner/decide-by
  regardless. New §7.1 Beta risk register maps isolation escape, secret
  leak, failed upgrade, and runaway execution to their mitigating stories.
  Three runbooks extend the E11 set: `e35_isolation_violation_incident.md`
  (config-level kill switch `AUTODEV_EXECUTION_ENVIRONMENT_BACKEND=unavailable`,
  reconstructing a run's isolation history from `EnvironmentManager`
  records), `e35_secret_leak_rotation.md` (rotate-then-revoke, redaction-
  contract verification), `e35_failed_upgrade_restore.md` (the three
  `autodev upgrade` outcomes — `ok`/`refused`/`backup_failed` — and the
  correct restore action for each). Also fixed doc drift found along the
  way: `decisions/README.md` still listed the three ADRs as Proposed, and
  E33's/E34's own progress.md entries still read "Not merged to `main`"
  after their PRs (#106, #107) had already landed.

- **2026-08-19** — **E35-S2 — Beta acceptance flow is complete, E35 now In
  progress · 2/3**. `docs/v2_platform/beta_acceptance_flow.md`: an
  executable checklist for gate criterion (1) — plan → approve (RBAC) →
  code/apply patch → validate in sandbox → evaluate — with each step's
  typed expected outcome and durable event evidence named
  (`backend/events/catalog.py`), plus four negative paths (permission
  denied, budget exhausted, isolation violation, secret revoked) each
  verified to end in a typed audited state with real, already-existing
  test coverage cited (no new test added — the pieces already exist; this
  composes them). A rehearsal procedure using only verified real CLI/API
  surfaces (`POST /v2/plans/{id}/steps/{n}/approve`,
  `GET /v2/sessions/{id}/runs`, `GET /v2/audit/access`) produces the gate
  evidence bundle a release candidate needs.

- **2026-08-19** — **E35-S1 — Expanded Beta gate & evidence mapping is
  complete, E35 now In progress · 1/3**. Split the combined isolation/
  secrets criterion in `v2_platform_reference.md` §18.9 into three
  separately assertable criteria (10 isolation/E32, 11 secrets/E33, 12
  clean-install-and-upgrade/E34). Added a 12-criterion evidence map to
  `beta_gap_analysis.md` §11, applying the "fact vs. recommendation"
  discipline (E35-S1-T3) rather than declaring the gate complete: 7
  criteria **Atendido** with named evidence, 2 **Parcial**, 3 honestly
  **Aberto** — the hybrid-retrieval benchmark has never run against a live
  environment (`phases/e7_context_rag.md` already says so), no test
  asserts the streaming-start latency target, and no staging environment
  exists to validate backup/restore against (`phases/e8_persistence_data.md`
  already says so too). Mirrored into `progress.md`'s own v2.0-beta
  wave-exit checklist, which pointed at nothing concrete before this.

- **2026-08-18** — **E34 — Packaging & Global Install (Beta) is complete
  (3/3)**, on `epic/e34-packaging-global-install` (branched from `main`
  after E33 merged via PR #106). **E34-S3** closed the epic: upgrade &
  version compatibility. `MigrationRunner.run_pending()`
  (`backend/persistence/migrations/runner.py`, shared by SQLite and
  PostgreSQL) now raises `SchemaVersionMismatchError` and refuses to run
  when a namespace's recorded schema version is newer than the installed
  code's migration list — protects every caller, not just the new command.
  `autodev upgrade [--backup-dir DIR] [--target-version X]`
  (`backend/ops/upgrade.py`) backs up the state/artifact stores first,
  reusing the E8-S4 `BackupManager` contract, and only then attempts to
  migrate; a refused upgrade still leaves a fresh backup behind. Rollback
  posture is documented as restore-from-backup with the existing E8-S4
  tooling (`docs/execution/upgrade.md`) — no bespoke rollback mechanism was
  built, since a migration's `down` step is frequently a no-op by design
  and was never meant to reconstruct dropped data. `--target-version`
  surfaces a best-effort `CHANGELOG.md` excerpt, deliberately minimal
  groundwork for the GA v1→v2 upgrade requirement (E13).

- **2026-08-18** — **E34-S2 — Self-host bootstrap & storage posture is
  complete, E34 now In progress · 2/3**. New `backend/ops/` package
  (distinct from `backend.config`/`backend.persistence`, matching E34's
  packaging/bootstrap/upgrade scope vs E14's CLI-UX scope):
  `backend/ops/doctor.py` runs five typed, ordered preflight checks
  (`settings`, `port`, `project_root`, `database`, `storage_backend`) —
  when `settings` itself fails, the dependent checks are skipped rather
  than run against configuration already known invalid.
  `backend/ops/bootstrap.py` runs the same preflight fail-closed, then
  initializes the configured state store by constructing it (schema
  migrations apply as an existing, idempotent side effect); safe to
  re-run. Storage posture (SQLite/local vs PostgreSQL/s3) turned out to
  already be explicit, fail-closed configuration
  (`Settings.validate_profile`, a pydantic `model_validator` that raises
  rather than silently choosing a side) — this story documented it in
  `docs/execution/cli-install.md` rather than reimplementing it. Bootstrap
  never accepts or writes a plaintext secret value; a deployment that
  needs secrets present creates them out-of-band via `autodev secrets
  create` (E33-S1). `autodev doctor` / `autodev bootstrap` CLI subcommands
  added to `backend/cli.py`.

- **2026-08-18** — **E34-S1 — Install strategy & packaging is complete,
  E34 now In progress · 1/3** (ADR-015 accepted). ADR-015 (Global
  Installation Strategy) resolved Proposed → Accepted: a hybrid of the
  already-strategy-agnostic `[project.scripts] autodev = "backend.cli:main"`
  console-script entry point (identical under `pip`/`pipx`/`uv tool`) for
  the CLI, plus the existing `docker-compose` bundle for self-host — no new
  packaging mechanism was needed. `autodev --version`
  (`backend/ops/version.py`) prints installed package version plus
  best-effort commit/build-date metadata
  (`AUTODEV_BUILD_COMMIT`/`AUTODEV_BUILD_DATE` overrides for a packaging
  step that wants reproducible provenance baked in; `"unknown"` for a
  plain source install). `scripts/verify_clean_install.sh` proves the
  install path with no repo checkout: builds a wheel from `backend/`,
  installs it into a fresh venv, and runs `autodev --version`/`autodev
  config validate` from a temp directory outside the repo. No installer
  script (`curl | sh`) was built — not justified over `pip`/`pipx`/`uv`
  without adoption feedback demanding it, per the ADR's own recommendation.

- **2026-08-18** — **E33 — Secrets & Credential Governance (Beta) is
  complete (3/3)**, on `epic/e33-secrets-credential-governance` (branched
  from `epic/e32-isolated-execution-beta`, itself not yet merged to
  `main`). **E33-S3** closed the epic: rotation takes effect on the very
  next `EnvironmentManager.provision()`/`bind_environment()` call (nothing
  caches a resolved value across provisions, so there is no propagation
  delay to reason about); a revoked reference is skipped at the injection
  boundary rather than failing the whole environment (`SecretStore`
  itself still fails closed with `SecretRevokedError` for any direct
  resolution attempt); rotate/revoke event-emission tests close out the
  audit-coverage DoD alongside S1/S2's create/resolve coverage. The
  v2.0-beta gate's "no plaintext secrets" criterion is evidenced here
  (redaction + audit tests, `docs/security/secrets.md`) but the actual
  checklist row in §18.9 is left to E35-S1-T1 (Beta Readiness Gates &
  Evidence), which explicitly owns expanding that gate with the E32/E33/E34
  criteria — not duplicating that edit here keeps one epic from silently
  pre-empting another's DoD. See the S1/S2 entries below for the store,
  crypto, injection, and redaction implementation. **Not merged to
  `main`.**

- **2026-08-18** — **E33-S2 — Injection into execution environments &
  redaction is complete, E33 now In progress · 2/3** (branch
  `epic/e33-secrets-credential-governance`, story
  `story/e33-s2-injection-and-redaction`). Secrets materialize only inside
  the E32 environment's process: `EnvironmentProfile.env_allowlist` (E32-S2's
  existing declaration surface -- no second one added) is resolved by
  `EnvironmentManager.resolve_secrets_for_profile()` at `bind_environment()`
  time and threaded through the new
  `ValidationJob.extra_env`/`SandboxRunner._run_docker`/`_run_local`
  (`backend/validation/`) as `--env`/subprocess-env, never through model
  context or plan/patch artifacts. Redaction (`backend/secret_store/redaction.py`):
  an exact-value `SecretRedactor` scrubs every task's stdout/diff *before*
  `EnvironmentManager.collect_artifacts()` persists it, and a process-wide
  registry scrubs every emitted event's `data` payload inside
  `emit_event()` itself (`backend/events/runtime.py`) -- every producer
  protected, not just environment events. A task that echoes a secret's
  value produces redacted evidence and a durable `secret.leak.suspected`
  audit event (catalog 51, unchanged count -- reserved in S1). Scope
  reduction stated honestly (`docs/security/secrets.md`): exact-value
  redaction is guaranteed, entropy-based detection of unknown
  secret-shaped strings is not attempted at all (not "best-effort").

- **2026-08-18** — **E33-S1 — Secret store abstraction & format decision is
  complete, E33 now In progress · 1/3** (branch
  `epic/e33-secrets-credential-governance`, story
  `story/e33-s1-secret-store-abstraction`; ADR-014 accepted). New module
  `backend/secret_store/` (named to avoid shadowing the stdlib `secrets`
  module): `SecretReference`/`SecretMetadata`/`SecretStatus` contracts that
  never carry a value; `crypto.py` reuses the Fernet envelope-encryption
  primitive already established for browser refresh tokens
  (`backend.auth.crypto.derive_fernet`), keyed by
  `AUTODEV_SECRET_ENCRYPTION_KEY`; `SecretStore` (SQLite-backed, versioned,
  scoped to `tenant_id/project/name`, mirroring the `backend/quotas/` and
  `backend/environments/` self-contained-store precedent rather than the
  core persistence migration runner — see ADR-014's stated scope
  reduction); `SecretService` wraps crypto + store and durably audits
  every create/rotate/revoke/resolve (`secret.created`/`.rotated`/
  `.revoked`/`.resolved`, catalog 46 → 51 with `secret.leak.suspected`
  reserved for E33-S2's leak fixture). RBAC: `secret:use` (VIEWER+, read
  metadata only) and `secret:manage` (ADMIN+, create/rotate/revoke),
  mirroring the `quota:read`/`quota:admin` split. REST:
  `backend/api/routers/secrets_v2.py` (auto-discovered, no manual
  registration) — every response model carries metadata only, so "no API
  returns a stored value" holds structurally. CLI: `autodev secrets
  create|rotate|revoke|list`, value always via `--value-stdin`, never a
  CLI argument. Docs: `docs/security/secrets.md`,
  `docs/v2_platform/decisions/ADR-014-secret-store-format.md` (Proposed ->
  Accepted). Not yet built (E33-S2/S3 scope): injection into E32
  environments, redaction, rotation-triggered fixture testing.

- **2026-08-18** — **E32 — Isolated Execution Environment (Beta slice) is
  complete (4/4)**, on `epic/e32-isolated-execution-beta` (branched from
  `main` after E14 merged via PR #104). ADR-013 accepted: hardened
  container (`backend/environments/backends.py::HardenedContainerBackend`,
  built on E14-S4's `SandboxRunner`) is the Beta default behind a
  backend-agnostic `EnvironmentBackend` protocol
  (`backend/environments/contracts.py`); `UnavailableBackend` is the
  fail-closed sentinel a typo'd `AUTODEV_EXECUTION_ENVIRONMENT_BACKEND`
  resolves to (unset resolves to the default, never to a silent guess).
  **E32-S2** added durably audited, fail-closed network/filesystem policy
  checks (`backend/environments/policy.py`) — a declared network allowlist
  that the Beta backend cannot mechanically enforce denies provisioning
  outright rather than silently over- or under-granting access. **E32-S3**
  added the provision → execute → collect → teardown lifecycle
  (`EnvironmentManager`, `EnvironmentStore`) wired into
  `OrchestratorService._process_tasks`: one environment per dispatch
  batch, a per-tenant concurrency ceiling
  (`AUTODEV_ENVIRONMENT_MAX_CONCURRENT`), TTL-based orphan reaping
  (`AUTODEV_ENVIRONMENT_TTL_SECONDS`), and best-effort artifact egress
  (stdout/diff) through the existing E0/E8 artifact store — a storage
  failure is logged and skipped, never fails the run. **E32-S4** added an
  additive `environment` field to every `ExecutionResult`
  (`backend/execution/contracts.py`) and four append-only catalog events
  (`environment.instance.provisioned`/`environment.access.allowed`/
  `.denied`/`environment.instance.retired`; catalog 42 → 46), so
  `EnvironmentManager.list_for_run`/`.list_decisions_for_run` let an
  auditor reconstruct a run's isolation history from durable records
  alone. Two scope boundaries recorded honestly rather than silently
  narrowed (`docs/environments/beta_isolation.md`): no plugin-facing
  `execution_environment` `ExtensionPointKind` yet (the protocol is
  code-level backend-agnostic, not SDK-wired), and workspace provisioning
  binds to the orchestrator's existing `project_root` rather than a fresh
  ref-pinned checkout — both deferred to E28, which is the actual
  consumer of the SDK wiring and the snapshot mechanism a real checkout
  step would feed. Docs: `docs/environments/beta_isolation.md`,
  `docs/v2_platform/decisions/ADR-013-beta-isolation-backend.md`
  (Proposed -> Accepted).

- **2026-08-17** — **E14 — Real Task Execution & Governed Autonomy is
  complete (7/7)**, on `epic/e14-real-execution-governance`, merged to
  `main` via PR #104 on 2026-08-17.
  **E14-S7 — `autodev` CLI Packaging & Install** closed the epic: no new
  packaging mechanism was needed (`backend/pyproject.toml`'s
  `[project.scripts] autodev = "backend.cli:main"` predates this story);
  `autodev` with no args now starts uvicorn + opens the browser at E18's
  existing root descriptor (`AUTODEV_HOST`/`AUTODEV_PORT` overrides,
  `Ctrl+C` to stop); `--command "<goal>"` now works standalone (previously
  only meaningful with `--shell`); `autodev permissions list|revoke`
  mirrors E14-S5's dynamic-permissions panel over HTTP. Docs:
  `docs/execution/cli-install.md`. No standalone binary/native installer
  was built — `pip install -e backend/` is the documented, tested path;
  a native installer would be its own ADR-worthy packaging decision the
  story's DoR didn't require.

  Epic summary across all 7 stories: `OrchestratorService.execute_plan`
  went from a pure simulation (S1's own "v1 precursor" framing) to a real,
  policy-gated (S2), mode-aware (S3, approval/auto/hybrid with durable
  pause/resume), hardened (S4, three dedicated sandbox-backed runners),
  and fully operable (S5 Web UX, S6 governed shell, S7 packaging) executor.
  Two RFC/ADR pairs (RFC-009/ADR-021 for the action/result contract,
  RFC-010/ADR-022 for the policy engine) were filed before their
  respective implementations, per the epic's own gate. Every story stated
  its scope reductions explicitly rather than silently narrowing DoD (no
  pre-approval diff preview, no cancel endpoint, no live shell SSE
  streaming, no native installer) — see each story's `docs/execution/*.md`.
  The Beta exit criterion this epic anchors remains open pending a
  dedicated wave-gate evidence pass across every Beta anchor epic (see
  the epic exit checklist in the phase doc) — not a gap in E14 itself.

- **2026-08-17** — **E14-S6 — Governed Interactive Shell is complete, E14
  now In progress · 6/7**. `autodev --shell` (`backend/cli_shell.py`) — a
  REPL that talks only to `/v2` over HTTP, never
  `backend.orchestrator`/`backend.execution`/`backend.persistence` or any
  other backend module (a static-analysis AST-import contract test
  enforces this). Flow: create session -> post a turn (drives the agent
  pipeline the plan is derived from) -> execute under the active mode
  (`--mode auto|approval|hybrid`) -> condensed per-task summary. A run
  that pauses shows its pending decision inline (approve/approve-always/
  deny, the same vocabulary as E14-S5's Web UX) and resumes automatically.
  `--command "<goal>"` runs one goal non-interactively. `backend/cli.py`
  gained a top-level `--shell`/`--mode`/`--command`/`--base-url` alongside
  its existing required-subcommand parser (`required=False` now, with an
  explicit `parser.error()` preserving the old "a command is required"
  behavior when neither is given); existing subcommands are unchanged,
  documented as out of this story's scope in `docs/execution/shell.md`.
  Scope note: no live SSE streaming in the shell — the synchronous
  execute/resume response already carries every result for a condensed
  summary, avoiding an indefinitely-open stream with no clean end signal;
  a follow-up could reuse E14-S5's already-proven SSE consumption pattern.
  **Not merged to `main`** — E14 has 1 more story (S7 CLI packaging).

- **2026-08-17** — **E14-S5 — Web UX for Governed Execution is complete,
  E14 now In progress · 5/7**. New `/execution` screen
  (`frontend/app/execution/page.tsx`, added to the primary nav rail):
  pending-decision approve-once/approve-always/deny
  (`ActionApprovalPanel`), dynamic-permission list/revoke
  (`DynamicPermissionsList`), and a real-time `execution.action.*` log
  (`ExecutionActionLog`) plus a resume control — wired exclusively to
  `/v2/execution/*` (`frontend/lib/execution_v2.ts`) and the E9-S2 SSE
  transport. The plan called for extending `lib/timeline.ts`'s
  `applyTimelineEvent`; reading it showed its 4-stage
  planning/analysis/patch/validation model doesn't fit
  `execution.action.*` events (different payload shape, no stage), so a
  small parallel module (`lib/execution_events.ts`) reuses the same SSE
  transport primitives instead — the transport itself needed zero
  server-side changes, confirming the S5/S6/S7 research. One Storybook
  story file per new component (axe a11y caught and fixed a real
  `text-ds-fg-3`-at-12px contrast failure before merge) and one Playwright
  e2e spec (`e2e/execution-approval.spec.ts`), matching the existing
  per-screen coverage bar. Scope reductions stated in
  `docs/execution/web-ux.md`: no pre-approval diff preview (nothing to
  preview before an action runs) and no cancel button (E14-S3 never shipped
  a cancel endpoint). **Not merged to `main`** — E14 has 2 more stories (S6
  governed shell, S7 CLI packaging).

- **2026-08-17** — **E14-S4 — Sandbox-Backed Runners is complete, E14 now
  In progress · 4/7**. `InProcessActionRunner` split into three dedicated
  runners behind the unchanged `ActionRunner` protocol: `CommandRunner`
  (`run_command`, hardened Docker sandbox, no network by default),
  `PatchRunner` (`create_file`/`edit_file`/`apply_patch`, E0 patch engine,
  structurally incapable of reaching `subprocess`), `ValidationRunner`
  (`run_validation`, shares the sandbox with `CommandRunner` but stays a
  separate class for independent future hardening).
  `CompositeActionRunner` dispatches by action type; `InProcessActionRunner`
  is now a backward-compatible alias for it — same constructor signature,
  same contract, zero caller changes. Reused the existing E11-S4
  real-Docker sandbox contract test (one new assertion that `CommandRunner`
  routes through the identical `SandboxPolicy`) rather than duplicating it;
  added a fail-closed-without-Docker unit test at the `ExecutionAction`
  layer. Docs: `docs/execution/engine.md`. **Not merged to `main`** — E14
  has 3 more stories (S5 Web UX, S6 governed shell, S7 CLI packaging).

- **2026-08-17** — **E14-S3 — Execution Modes (Approval, Auto, Hybrid) is
  complete, E14 now In progress · 3/7**. `OrchestratorService.execute_plan`
  gains an optional `mode` parameter (`ExecutionMode`, default `auto` —
  byte-for-byte unchanged behavior from S1/S2). `approval` mode pauses
  every task with a derived action for a human decision; `hybrid` pauses
  only when E14-S2's policy engine doesn't cover it (`matched=False`),
  auto-executing what it does cover. A pause does not block the request:
  it durably records a `PendingDecision`
  (`backend/execution/decisions.py`, reusing E3-S4's pause/decide/expire
  *pattern* — not its Flow-Engine-bound code, which
  `OrchestratorService`'s run/task model doesn't share — and the existing
  `run.human.requested`/`.resolved` events, so no new event types were
  needed), marks that step `awaiting_approval`, and **stops processing
  further tasks**, persisting everything completed so far. `resume_plan_execution`
  continues a paused run by re-deriving the plan and skipping every
  terminal step — no task-list snapshot is persisted; `mode` is a
  per-call parameter passed again on resume, not stored run state.
  Hybrid's "always" option persists a dynamic permission
  (`PolicyService.grant_dynamic_permission`) so equivalent future actions
  auto-allow without pausing again; "deny" fails just that task and
  execution continues; a pending decision past its deadline
  (`AUTODEV_EXECUTION_DECISION_TIMEOUT_SECONDS`, default 3600s)
  self-expires to `timed_out` on next read and is treated as deny-and-stop,
  per the story's documented timeout fallback. REST:
  `POST /v2/sessions/{id}/execution-plan/{execute,resume}` (mode-aware),
  `GET /v2/execution/decisions` + `POST .../resolve`,
  `GET/DELETE /v2/execution/policy/dynamic`. Docs: `docs/execution/modes.md`.
  **Not merged to `main`** — E14 has 4 more stories.

- **2026-08-17** — **E14-S2 — Permission & Policy Engine is complete, E14
  now In progress · 2/7** (RFC-010 + ADR-022 accepted first, per the epic's
  gate). Every action `TaskExecutor` dispatches is now gated by
  `PolicyService.evaluate` (`backend/execution/policy.py`) before it
  reaches the runner: category-scoped allow/deny rules (`shell`,
  `fs-write`, `patch`, `network`, `secrets-read`, `validation`), a durable
  per-decision audit trail, and two additive events
  (`execution.policy.allowed`/`.denied`, 40 → 42 catalog types). Mirrors
  `QuotaService`'s already-accepted resolution rule (ADR-019): a tenant
  with any stored rule is governed by exactly those; a tenant with none
  fails closed in production and falls back to a permissive default
  outside production, preserving the Alpha gate's local-first guarantee —
  a policy engine that blocked everything by default locally would have
  regressed `test_local_first_mode.py`. Precedence when multiple rules
  match: specificity (dynamic-permission-with-pattern > static-with-pattern
  > dynamic-without-pattern > static-without-pattern) before effect,
  explicit `deny` winning ties within the top tier — this lets a future
  hybrid-mode "always" grant carve an exception out of a broader static
  deny while a specific static deny still overrides a broad static allow.
  REST: `GET/POST /v2/execution/policy` (`policy:read`/`policy:admin`).
  Dynamic-permission REST endpoints deliberately deferred to E14-S3, which
  is what actually grants them. **Not merged to `main`** — E14 has 5 more
  stories.

- **2026-08-17** — **E14 kicked off — E14-S1 (Real Task Executor) complete,
  E14 now In progress · 1/7** (branch `epic/e14-real-execution-governance`,
  story `story/e14-s1-real-task-executor`; RFC-009 + ADR-021 accepted per the
  epic's exit checklist). `OrchestratorService.execute_plan` no longer
  simulates: `TaskExecutor` (`backend/execution/executor.py`) maps each
  derived `ExecutionTask` to zero or more `ExecutionAction`s and dispatches
  them to `InProcessActionRunner` (`backend/execution/runner.py`), which
  reuses the existing E0 patch engine (`backend/patches/engine.py`) for
  file/patch actions and the v1 `SandboxRunner` precursor
  (`backend/validation/sandbox.py`) for command/validation actions — no new
  sandboxing was built in this story (that is E14-S4). `validation`-category
  tasks naming a known tool (pytest/ruff/npm/python) now run through the
  sandbox; `implementation`-category tasks now write a real, observable
  execution-note file under `.autodev/execution-notes/`; other categories
  still derive no action. `StepStatus` gained `FAILED` so a task with a
  failed action is reported as such; `OrchestratorRun`/`RunStep`/
  `AgentExecution` external shapes are unchanged, so the three existing
  callers (`sessions_v2.py`, `api/main.py`, `cli.py`) needed no changes.
  Both the patch-write path and the sandbox stay fail-closed by default
  (`AUTODEV_ENABLE_PATCH_APPLY`/`AUTODEV_ENABLE_SANDBOX`, both off), so
  default behavior for existing callers is unchanged until an operator opts
  in. Three additive events (`execution.action.started`/`.completed`/
  `.failed`) join `EVENT_CATALOG` (37 → 40 types). No policy/permission
  engine yet (E14-S2), no execution modes (E14-S3) — see
  `docs/execution/engine.md` for the full scope boundary. **Not merged to
  `main`** — E14 has 6 more stories before the epic → `main` PR.

- **2026-08-17** — **E11-S3 — Multi-tenant and quotas/budgets is complete**
  (dependencies E8, E4, E11-S2 Done; see ADR-019). **E11 is now 4/4 Done.**
  T1 closed real cross-tenant leaks by threading the E11-S2 principal's
  tenant through every Control Plane route that had been hardcoding
  `DEFAULT_TENANT_ID` or trusting a client-supplied selector — including
  `GET /v2/context/retrieve` (the gap S2 flagged) and, found during this
  story's own review rather than left latent, `chat_v2.py`'s turn endpoints
  (`POST`/`GET /v2/sessions/{id}/turns`, `GET /v2/turns/{id}`), which had
  never resolved the authenticated principal at all — any caller could post
  into or read another tenant's session turns. T2 landed a durable
  per-tenant quota/budget layer (`backend/quotas/`: policy CAS, concurrency
  leases, storage reservations, monthly usage windows, request-rate
  buckets) wired into `GET/PUT /v2/quotas/usage|policy` (`quota:read`/
  `quota:admin`), `autodev quotas get|set`, per-tenant storage reservation
  on artifact writes, and per-credential request-rate admission in the one
  app-level auth dependency every `/v2` route already runs through. T3
  enforces budgets in both places the story's CF asks for: the Agent
  Runtime gets fail-closed concurrent-run admission (a lease acquired
  before a run record exists, released unconditionally on success or
  failure); the Reasoning Engine narrows every run's token/cost/wall-clock/
  step ceiling to the tenant's `default_run_budget` and records real
  monthly usage after each run, without letting a post-hoc monthly-limit
  denial corrupt an already-completed result. Four `autodev_quota_*`
  OpenTelemetry gauges (mirroring E11-S1's backup-gauge pattern) back a new
  Grafana dashboard (`infrastructure/observability/grafana/dashboards/quotas.json`).
  Deliberately not built here, and said so in the phase doc rather than
  silently left: real per-call LLM cost/token accounting in the older
  LangGraph `OrchestratorService` agent pipeline (still hardcoded
  `costUsd: 0.0`/`tokens: 0`, pre-existing, E14's job) and E5's cost-aware
  model selection actually enforcing `respect_tenant_quota` (parsed only,
  needs a larger selection-signature change). **Merged to `main`.**

- **2026-08-15** — **E11-S2 — RBAC and authentication is complete**
  (dependency E9-S1 Done; see ADR-018). Real Control Plane authentication
  and authorization replace the permissive placeholder: OIDC bearer JWTs
  (full `iss`/`aud`/`exp`/tenant/role/scope claim + JWKS-signature
  validation, algorithm allowlist never inferred from the token header),
  governed hash-only service keys (`adk_live_...`, 1–90 day expiry,
  immediately revocable, `autodev auth service-key create|list|revoke`),
  and browser sessions via OIDC authorization-code + PKCE (HttpOnly/Secure
  cookie, encrypted refresh token). Canonical five-role RBAC
  (`viewer`<`operator`<`maintainer`<`admin`<`owner`; legacy `author` accepted
  only as an input alias for `maintainer`) enforced by one global FastAPI
  dependency, covering every route across all 26 `backend/api/routers/*.py`
  modules including auto-discovered plugin routers — a repo-wide contract
  test (`test_every_non_public_route_declares_policy`) now fails CI if a new
  route ships unannotated. Local zero-config access is unchanged; production
  startup refuses to serve traffic without complete OIDC/JWKS settings or an
  active service credential. Every allow/deny decision against a resolved
  principal is durably audited before the caller sees the result — a
  required-audit-write failure denies an otherwise-allowed request
  (`503 security.audit_unavailable`) rather than letting an unauditable
  allow through — retrievable per-tenant via `GET /v2/audit/access`.
  Closed the "trusted actor" gap by name: flow human-decisions and every
  plan-approval/plan mutation now record the authenticated principal as the
  actor, never a client-supplied body/query field. OpenAPI now publishes
  `oidcBearer`/`serviceBearer`/`sessionCookie` security schemes and derives
  each operation's `x-autodev-required-scope` directly from its
  `@requires_scope` declaration — no second, hand-maintained scope registry.
  Flagged for E11-S3, not fixed here (no per-resource tenant data exists
  yet): `GET /v2/context/retrieve` accepts a caller-supplied `tenant_id`
  query parameter with no check against the authenticated principal.

- **2026-08-15** — **E11-S4 — Execution security and runbooks is complete**
  (story `E11-S4-T1`-`T3` done; dependencies E1, E8-S4). Trusted-only
  in-process plugin boundary (ADR-020): production requires an explicit
  `AUTODEV_TRUSTED_IN_PROCESS_PLUGINS` grant and still rejects
  `runtime.isolation` or privileged-permission `in-process` plugins. The
  validation sandbox is now driven by one typed `SandboxPolicy`: read-only
  root filesystem with a bounded `/tmp`, a read-only mount of only the
  resolved/guarded workspace (a `cwd` escaping `AUTODEV_PROJECT_ROOT` is
  blocked before any process spawns), a bounded timeout (return code `124`
  on kill), and a real-Docker security contract
  (`backend/tests/integration/test_sandbox_security_contract.py`) that is a
  mandatory, non-skippable CI gate. `make run_secret_scanning` now scans the
  full working tree (tracked and untracked) via a read-only bind mount, not
  a stale container-image copy. The Trivy SCA gate widened from
  CRITICAL-only/vuln-only/ignore-unfixed to
  `HIGH,CRITICAL`/`vuln,license`/`ignore-unfixed: false`, gated by an
  expiring-exception policy (`.trivyignore.yaml`,
  `scripts/validate_security_exceptions.py`). `Settings.redacted_model_dump()`
  is now the sole credential-redaction policy (`DATABASE_URL`/
  `AUTODEV_REDIS_URL` masked when they embed a password;
  `AUTODEV_MINIO_ACCESS_KEY`/`_SECRET_KEY` always masked), production rejects
  an empty or known-default PostgreSQL/MinIO credential, and
  `infrastructure/docker-compose.yml` no longer bakes in a fallback
  credential. PostgreSQL backup/restore now fails closed when configured but
  missing `pg_dump`/`pg_restore` (previously silently skipped), passes the
  database password only via `PGPASSWORD` (never argv/error text), and
  records every attempt to a durable, sanitized, `0600` status file exposed
  as `autodev_backup_*` Prometheus gauges through the E11-S1 meter.
  `AutoDevBackupNeverSucceeded`/`AutoDevBackupStale`/`AutoDevBackupFailing`
  alert through a new Alertmanager service under the existing
  `observability` Compose profile, each linking
  `docs/v2_platform/runbooks/e11_incident_response.md`. Live-verified:
  `promtool check rules` and `amtool check-config` both SUCCESS; a live
  Prometheus instance confirmed `activeAlertmanagers` reachable and the
  `autodev-e11-s4-backup` rule group evaluating (`AutoDevBackupNeverSucceeded`
  correctly `pending` with no prior backup). This story was implemented in a
  separate worktree in parallel with E11-S2 (both depend only on E11-S1);
  epic-level story count and "Next action" above are reconciled by whichever
  story lands second.

- **2026-08-15** — **E11-S1 — Observability (OpenTelemetry) is complete**
  (Beta epic **E11 now 1/4 In Progress**; dependency E0 Done). Correlated
  traces/metrics/logs by `run_id`/32-character W3C `trace_id`; self-hosted
  OpenTelemetry Collector + Prometheus + Tempo + Loki + Grafana stack behind
  the `observability` Compose profile (`make observability-up|verify|down`,
  ADR-017); configurable sampling (`OTEL_TRACES_SAMPLER`/`_ARG`) and
  per-signal retention (`AUTODEV_OBSERVABILITY_TRACE_RETENTION`/
  `_METRIC_RETENTION`/`_LOG_RETENTION`); `OTEL_ENABLED=false` emergency
  rollback. Instrumentation overhead verified at ~2.6–2.8% (target <5%) after
  caching the runtime's tracer lookup and switching the benchmark's
  synthetic I/O wait from `time.sleep` to a monotonic busy-wait, which
  otherwise buried the ~80us/operation instrumentation signal under this
  environment's OS scheduler jitter (`scripts/measure_observability_overhead.py`).
  Live-verified: `make observability-up && make observability-verify` reports
  Grafana/Prometheus/Tempo/Loki all healthy, including a fix for Prometheus's
  default scrape relabeling silently overwriting the exporter's own `job`
  label (`honor_labels: true`). Next: E11-S2 (RBAC and authentication).
- **2026-08-17** — **Gap-closure pass on `epic/gap-closure-alpha`** (no new
  epic opened, per the "feche os gaps" protocol in the root `CLAUDE.md`).

  **Process note: this pass duplicated work that was already sitting in two open
  pull requests.** PR #98 (`epic/e2-agent-framework`, opened 2026-08-10) already
  corrected the E2 phase-doc status, and PR #99 (`epic/e7-context-rag`, same day)
  already implemented the E7 indexing and context tracing. Open PRs were not
  checked before starting, so both were re-done from scratch and had to be
  reconciled on merge. Check `gh pr list` before opening a gap-closure pass.

  *Tracker corrections.* `phases/e2_agent_framework.md` still read "In Progress
  · 5/6" after E2-S6 merged to `main` (88de5e7) — corrected to Done · 6/6 (also
  fixed independently by PR #98).
  **E11 was tracked as `Not started · 0/4` while E11-S1, E11-S2 and E11-S4 were
  already merged** on `epic/e11-observability-security-multitenant`, with
  E11-S3 in progress on its story branch; the row is now `In progress · 3/4`
  with an explicit note that none of it is on `main`, and the "Next action"
  pointer — which was aiming at the already-finished E11-S1 — now points at
  finishing E11-S3 and opening the epic → `main` PR. Story total 71 → 74.

  *E17 fast-follow closed.* `frontend/app/page.tsx` now consumes the
  `?sessionId=` deep link `SessionRow` has been emitting since E17-S4, behind
  the Suspense boundary `useSearchParams` requires; a stale id degrades to the
  most recent session plus a localized notice. Covered by
  `frontend/e2e/chat-resume-session.spec.ts` (3 cases).

  *E7 deferred DoD items.* Four of five closed: `autodev.repository.index` /
  `.reindex` spans (E7-S1), `autodev.context.compose` + per-provider spans with
  worker-thread context propagation (E7-S4), `docs/context/retrieval.md`
  covering language support and RRF configuration (E7-S1/E7-S3), and a
  retrieval recall/latency benchmark — `backend/repository/retrieval/benchmark.py`
  plus the `scripts/benchmark_retrieval.py` CLI with `--max-p95-ms` /
  `--min-recall` gating (E7-S2). All span attributes are counts and ids only:
  no paths, no chunk content, no provider exception messages. **No retrieval
  numbers are claimed** — producing them needs a live PostgreSQL + pgvector and
  a curated label set, so the v2.0-beta hybrid-retrieval CNF stays unverified.
  Still open: feeding retrieval metrics into the Evaluation Service (E7-S3).

  *v2.0-alpha wave gate walked and met.* Four of five criteria had never been
  ticked despite every Alpha anchor epic being Done. Each now names its
  evidence; two new tests were written to supply it —
  `backend/tests/integration/test_alpha_gate_flow_replay.py` (agent-plugin flow
  + durable state + event-store reconstruction + deterministic replay, as one
  path) and `backend/tests/integration/test_local_first_mode.py` (defaults
  resolve to SQLite + stub provider with every non-loopback socket blocked, and
  a third test proving the guard itself fires).

  *Defects found, recorded, deliberately not fixed* (doc-drift D2/D3): the
  in-process plugin import sandbox denies transitive **host** imports, so a
  cold process quarantines `autodev/agent-coder` and
  `test_flows_api.py::TestAgentFlowEndToEnd` only passes when its file's earlier
  tests run first; and `ContextComposer.compose` blocks until every worker
  finishes despite its per-provider timeout, contradicting its own docstring.
  Both touch a boundary (a security control, a concurrency contract) where the
  fix is a decision, not a patch.

- **2026-08-10** — **E2-S6 composition — closed the gap between the tracker and
  the code.** A post-merge review of `7708430..b69dbd9` found that the model
  gateway had **no production caller**: nothing outside `backend/tests/` built a
  `ModelGateway`, every `AgentRuntime` was constructed without one, and
  `Settings.llm_model` was read by nothing in the repository. E2 was recorded here
  as **Done 6/6** while `phases/e2_agent_framework.md` still said **In Progress
  5/6** — and the story's headline criterion ("agents select provider-neutral
  model targets") was unreachable by any route. Closed by:
  (1) `backend/llm/composition.py`, a composition root building the registry and
  gateway behind `@lru_cache` factories that routers may import (they may not
  import `backend.api.main`); (2) `AgentNodeHandler` defaulting to
  `build_agent_runtime()` — the single real `AgentRuntime` construction site in
  the product; (3) unifying the model-config source on `RuntimeConfig.llm`, which
  `PUT /v2/provider-config` owns, with `LLM_MODEL` as an env-only override —
  previously the API wrote `OPENAI_MODEL` while the gateway helper expected
  `LLM_MODEL`, so a model configured through the versioned surface still produced
  `provider_not_configured` while `/status` reported it as configured;
  (4) cache invalidation on all three surfaces that write the LLM block
  (`/v2/provider-config`, `/v2/config`, legacy `PUT /config`) — the first two
  previously invalidated nothing.
  `provider: stub` deliberately composes **no** gateway, so the offline profile is
  behaviorally unchanged. Proof: `test_two_agents_use_distinct_models_in_one_flow_run`
  (the handoff's own completion criterion) plus 17 composition unit tests.
  **Security fix in the same change:** `backend/tests/conftest.py` gained an autouse
  fixture pinning `AUTODEV_CONFIG_PATH` to a per-test file and stripping credential
  environment variables. `RuntimeConfigService` resolves its path from the working
  directory, so once the gateway became the default the suite would have issued
  live, credentialed calls against whatever provider the developer had configured
  locally. Still open and documented rather than fixed: `timeoutSeconds` reports
  instead of bounding; `retries` only fires for codes also in `fallbackOn`;
  capabilities are per-adapter, not per-model; streaming/structured-output/tool
  calls still have no product consumer.

- **2026-08-10** — **E7 deferred-DoD closure (observability + fusion config).**
  Closed three of the five DoD items E7 carried into Done: indexing traces
  (`autodev.repo.index` / `autodev.repo.reindex` spans), per-step context traces
  (`autodev.context.compose` with a per-provider event), and fusion
  configuration. The last was not merely undocumented — `reciprocal_rank_fusion`
  accepted `k`/`weights` but `retrieve()` neither accepted nor forwarded them, so
  fusion was unconfigurable from every caller including HTTP; `fusion_k`,
  `lexical_weight` and `vector_weight` are now first-class on
  `GET /v2/context/retrieve`, echoed back in a `fusion` block, and documented in
  `docs/api/context_retrieval.md`. Remaining deferrals and why they stay deferred
  are recorded in the epic checklist: language support is unmet in code (Python
  only), the recall/latency benchmark needs a live pgvector instance, and
  retrieval metrics in the Evaluation Service are a new surface rather than
  wiring.
  **Also corrected stale documentation across four files**: `SupervisorPolicy`
  was described as pending "not wired" debt in `feature_matrix.md`,
  `dynamic_orchestration.md`, and the E3/E5 phase docs. It is **superseded**, not
  pending — a 22-line sequential cursor that ignores run state, replaced by E5's
  policy-driven `backend/routing/` Router/Selector, imported by nothing but its
  own unit test. The genuinely open item, now stated where the stale claims were,
  is that the Router/Selector is itself not wired into `POST /chat/dynamic`, whose
  graph compiles to a fixed linear chain with no conditional edges.
  (`v2_platform_reference.md`'s mention is in the "v1" column of a v1→v2
  comparison table and is correct as historical framing; left unchanged.)

  **Superseded in part by the 2026-08-17 entry above.** That pass duplicated the
  observability half of this work before this branch merged. On reconciliation
  the spans already on `main` were kept, so the span names this entry describes
  (`autodev.repo.*`, and a per-provider *event* on the compose span) are not what
  shipped — see the merged E7 phase-doc checklist. The fusion-configuration work
  below is unaffected and is what makes this branch worth landing; its
  documentation moved from `docs/api/context_retrieval.md` into the consolidated
  `docs/context/retrieval.md`.

- **2026-08-05** — Opened corrective story **E2-S6 — Provider-neutral model
  gateway and governed fallback** (E2 temporarily **5/6 In Progress**; dependencies
  E0, E1, E2-S1–S4). ADR-016 accepts AutoDev-owned immutable contracts plus
  replaceable adapters and defers LiteLLM. Task 1 adds validated `agent.yaml` 2.1
  model configuration while retaining 2.0 and legacy string `policy.model` behavior.
  Explicit non-goals: parallel scheduling, A2A, shared-context ACLs, external coding
  agent harnesses, pricing catalogs, and UI redesign.

- **2026-07-22** — Planning-only, no implementation: added the **v2.3 —
  Platform Excellence** wave (**E36-E40**, 22 stories) to convert the architecture
  review recommendations into executable planning slices: document authority +
  SDD operating model; context-independent phase handoffs plus harness
  engineering and looping engineering; SOTA evidence matrix + capability
  benchmark; product modes + agentic threat model + minimum FinOps; and
  architecture fitness functions + local-first degradation.

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
  new **v2.1 wave** in §18.9, Contents entry), six phase docs
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
