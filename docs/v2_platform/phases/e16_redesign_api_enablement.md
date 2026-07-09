# E16 — Frontend Redesign: Control-Plane API Enablement

**Wave:** Beta — sequenced logically after E10 (base Design System) and executed
before E11; feeds the Control Center screens epic (E17).
**Status:** Done (4/4 complete)
**Depends on:** E9 (Control Plane API /v2 core, streaming, event catalog, MCP),
E3 (orchestration engine / plan store), E8-S1 (persistence core) — plus the
E1/E2/E6 catalogs (plugin registry, agent registry, skills registry) that
E16-S4 aggregates read-only.
**Enables:** E17 (Control Center Screens, which consume every `/v2` endpoint
added here); E14-S5 (Web UX for Governed Execution, which reuses the E16-S2
step-level approval gates and the E16-S3 patch review/apply contracts).
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.10

## Objective

Close the API-first gap between the "Execution Control Center" redesign
prototype (`layout_prototype_brainstorm/`) and the current backend surface.
Every capability the prototype's screens will need — a chat/execution
timeline with per-step monospace output, plan step approval gates, patch
review/apply, and an extensions/provider sidebar — must exist as a versioned
`/v2` endpoint (or event) before E17 builds a single screen against it, per
the repository's API-first rule (`docs/architecture/v2_platform_reference.md`
§2.13: Web UI, CLI, and MCP are clients of `/v2` and never touch the State
Store or other internals directly). This epic does not deliver new product
capability; it re-exposes and adjusts capability already delivered by E0,
E1, E2, E3, E6, E9 so the redesigned frontend has something to consume.

## Key result

The four `/v2` surfaces below exist, are covered by contract tests, and are
documented — enabling E17 to build the timeline, plan-review, patch-review,
and extensions/provider screens purely against `/v2`, with zero direct calls
to the legacy root-relative endpoints (`frontend/lib/api.ts`) or to the
State Store.

1. `/v2` chat & execution-timeline contract (E16-S1).
2. `/v2` plans with step-level approval gates (E16-S2).
3. `/v2` patches review & apply (E16-S3).
4. `/v2` extensions & provider config (E16-S4).

## Stories

### E16-S1 — /v2 chat & execution timeline contract

Origin: E9-S2 (run streaming / SSE transport), E3 (orchestration engine),
E2 (agent roles Planner/Navigator/Analyzer/Coder/Validator).

Subtasks:
- `E16-S1-T1`: versioned `/v2` chat/turn endpoints (create turn, get turn,
  list turns for a session) with `schemaVersion`, replacing the legacy
  root-relative `POST /chat` (`frontend/lib/api.ts::sendChatMessage`) as the
  session-message contract the redesigned UI calls.
- `E16-S1-T2`: run-event taxonomy extending the E9-S3 event catalog to cover
  the prototype's live timeline stages — planning -> analysis -> patch ->
  validation — with each event carrying a per-step monospace output field
  (stdout/log excerpt), streamed over the existing `v2/runs/{id}/events/stream`
  SSE transport (E9-S2) rather than a new transport.
- `E16-S1-T3`: mapping of the E2 agent roles (Planner/Navigator/Analyzer/
  Coder/Validator) onto timeline step actors, so each streamed event is
  attributable to the agent role that produced it (drives the prototype's
  per-step role badges).

| Item | Content |
| --- | --- |
| CF | A client creates a turn via `/v2` and receives, via the existing SSE stream, an ordered sequence of typed events covering planning/analysis/patch/validation, each carrying actor role and monospace output; the legacy `POST /chat` contract is fully replaced (no UI code depends on it after this story) |
| CNF | Event delivery latency inherits E9-S2's < 1 s streaming start; new event types validate against a published schema; backward-compatible within a MAJOR (`schemaVersion`) |
| DoR (specific) | E9-S2 streaming transport and E9-S3 event catalog available; E3 plan/run execution states reviewed; RFC-006 (governance for additive `/v2` endpoints, sibling-authored) approved |
| DoD (specific) | Contract tests for the turn endpoints and the extended event taxonomy; `frontend/lib/api.ts::sendChatMessage` and its `chat`/`sessions/{id}/runs` callers migrated to the new contract in a later E17 story (not here — this story only adds the `/v2` surface); docs |
| Dependencies | E9-S1, E9-S2, E9-S3, E3-S2, E2-S1 |

### E16-S2 — /v2 plans with step-level approval gates

Origin: E3 (plan store), E9-S1 (Control Plane API core); aligns with the
E14 human-in-the-loop governance model so the same approval semantics are
not reinvented twice.

Subtasks:
- `E16-S2-T1`: `/v2` plan endpoints to list a session's plan and read
  individual step detail, and to edit a step's content prior to approval —
  a versioned successor to the legacy `sessions/{id}/execution-plan`
  (`frontend/lib/api.ts::getExecutionPlan`) and `plans/{sessionId}`
  (`frontend/lib/api_ext.ts::getPlan`) reads.
- `E16-S2-T2`: per-step approve/reject endpoints and an execute-approved
  endpoint that triggers execution only for steps in the approved state —
  a versioned, step-granular successor to the legacy all-or-nothing
  `sessions/{id}/execution-plan/execute` (`frontend/lib/api.ts::executePlan`).
- `E16-S2-T3`: plan state machine (`draft -> under_review -> approved |
  rejected -> executing -> completed`, per step and rolled up per plan) with
  associated `plan.step.*` events published on the E9-S3 event bus so the
  timeline (E16-S1) reflects approval decisions live.
- `E16-S2-T4`: this story does not introduce a Web UI — that is deferred to
  E17 — but it validates that E14-S3's three execution modes
  (approval/auto/hybrid) map cleanly onto the new state machine so E14-S5
  can reuse it rather than fork a second approval contract.

| Item | Content |
| --- | --- |
| CF | Listing a plan returns steps with their current state; approving/rejecting a step transitions only that step; execute-approved runs only steps in the approved state and refuses to run rejected/pending ones; every transition emits a `plan.step.*` event |
| CNF | State transitions are atomic (no partial step-state corruption under concurrent approve/reject); read p95 < 300 ms (inherits E9-S1 target); events validate against the E9-S3 schema |
| DoR (specific) | E3 plan store contract reviewed; E9-S1 core available; E14-S3's approval/auto/hybrid mode semantics reviewed for reuse (informational — E14-S3 is not a hard dependency) |
| DoD (specific) | Contract tests for every state transition, including illegal ones (e.g. execute a rejected step is denied); `docs/v2_platform` note describing the state machine; RFC-006 governance item closed for this endpoint group |
| Dependencies | E9-S1, E3-S2 |

### E16-S3 — /v2 patches review & apply

Origin: E0 (patch engine), E9-S1 (Control Plane API core), E14 (governance —
apply/discard follows the same fail-closed, auditable posture as E14's
governed execution, even though the E14 executor itself is a separate
epic).

Subtasks:
- `E16-S3-T1`: `/v2` changed-file list endpoint for a run/session, returning
  path plus added/removed line counts (+/− stats) per file — new surface;
  no legacy equivalent exists (`frontend/lib/api_ext.ts::generatePatch`
  only generates a single ad hoc diff from inline `original`/`updated`
  strings, it does not enumerate a run's changed files).
- `E16-S3-T2`: unified diff retrieval per changed file, plus an
  edited-content override endpoint so a reviewer can submit a modified
  version of a proposed patch before it is applied.
- `E16-S3-T3`: apply endpoint (dry-run by default, explicit flag required
  for a real apply) and a discard endpoint, both reusing the E0 patch
  engine rather than reimplementing patch application; apply is logged with
  actor/timestamp/result for auditability, consistent with E14's
  governance posture.
- `E16-S3-T4`: `patch.*` events (`patch.changed_files.listed`,
  `patch.applied`, `patch.discarded`) published on the E9-S3 event bus so
  the timeline (E16-S1) reflects patch outcomes live.

| Item | Content |
| --- | --- |
| CF | A client lists changed files with +/− stats for a run; retrieves a unified diff per file; submits an edited-content override; applies (dry-run by default) or discards; every apply is auditable (actor, timestamp, result) |
| CNF | Apply never mutates the repository outside the E0 patch engine's guarded path; dry-run is the default and a real apply requires an explicit parameter; read p95 < 300 ms |
| DoR (specific) | E0 patch engine contract reviewed; E9-S1 core available; RFC-006 governance item covers the new endpoint group |
| DoD (specific) | Contract tests including a rejected-apply-outside-guarded-path case; dry-run vs. real-apply behavior tested; docs |
| Dependencies | E9-S1, E0 (patch engine) |

### E16-S4 — /v2 extensions & provider config

Origin: E1 (plugin core), E2 (agent registry), E6 (skills registry), E9-S4
(MCP interoperability), E5 (routing/provider selection).

Subtasks:
- `E16-S4-T1`: unified extension catalog endpoint that aggregates agents,
  skills, plugins, and MCP servers into a single, typed listing for the
  prototype's extensions screen — composing the existing
  `v2/agents/catalog` (E9), `v2/skills` (E9), and `v2/plugins/active` (E9)
  documents plus the E9-S4 MCP server registrations, rather than
  introducing a second source of truth for any of them.
- `E16-S4-T2`: enable/disable action on a catalog entry (agent, skill,
  plugin, or MCP server), delegating to the owning subsystem's existing
  activation mechanism (E1 plugin lifecycle, E2 agent registry, E6 skill
  registry, E9-S4 MCP allowlist) instead of adding a parallel one.
- `E16-S4-T3`: create/edit endpoints scoped to agent extensions, covering
  system prompt, model selection, and allowed-tools list — new surface; no
  legacy equivalent exists (`frontend/lib/api_ext.ts::listAgents` is
  read-only).
- `E16-S4-T4`: provider config endpoint plus a live provider status read
  (name, model, health) for the shell's sidebar provider card — a
  versioned successor to the legacy root-relative `config`
  (`frontend/lib/api.ts::getRuntimeConfig` / `updateRuntimeConfig`),
  backed by E5's routing/provider selection state for the "live" health
  signal the legacy endpoint does not expose.

| Item | Content |
| --- | --- |
| CF | The extension catalog endpoint returns agents, skills, plugins, and MCP servers in one typed response; enable/disable delegates correctly to each subsystem; agent create/edit persists system prompt/model/allowed tools; provider config read/write works and provider status reflects live health |
| CNF | Enable/disable and create/edit changes take effect without a service restart; least-privilege is preserved (E9-S4-T3's MCP allowlist is not bypassed by the unified catalog); read p95 < 300 ms |
| DoR (specific) | E1 plugin lifecycle, E2 agent registry, E6 skill registry, E9-S4 MCP allowlist, and E5 provider selection all available and reviewed; RFC-006 governance item covers the new endpoint group |
| DoD (specific) | Contract tests per subsystem delegation (agent/skill/plugin/MCP enable-disable); agent create/edit validated against the existing agent manifest schema; docs |
| Dependencies | E9-S1, E9-S4, E1, E2, E6, E5 |

## v1 precursor / starting point

The redesign does not start from zero: most of the data these four stories
expose already exists behind non-versioned or partially-versioned
endpoints. This section maps what exists today, file by file, to the
`/v2` gap each story closes.

- **`frontend/lib/api.ts`** (legacy, root-relative, unversioned, no
  `schemaVersion`):
  - `getRuntimeConfig` / `updateRuntimeConfig` -> `GET|PUT config`. Gap
    closed by **E16-S4** (`/v2` provider config + live status; the legacy
    endpoint has no health signal).
  - `requestPlan` -> `POST plan`. Superseded by session creation
    (`v2/sessions`, already E9) plus **E16-S2**'s plan-read/approval
    surface.
  - `sendChatMessage` -> `POST chat`. Gap closed by **E16-S1** (`/v2`
    chat/turn endpoints + timeline events).
  - `listSessions` / `listRuns` -> `GET sessions`, `GET
    sessions/{id}/runs`. Already superseded by `v2/sessions` and
    `v2/sessions/{id}/runs` (E9-S1); no further gap for E16.
  - `getExecutionPlan` / `executePlan` -> `GET
    sessions/{id}/execution-plan`, `POST
    sessions/{id}/execution-plan/execute`. Gap closed by **E16-S2**
    (per-step approval instead of all-or-nothing execute).
  - `getRepositoryContext` -> `GET repository/context`. Out of scope for
    this epic (no story above touches repository search); remains a
    candidate for a future adjustment story outside E16-S1..S4.

- **`frontend/lib/api_ext.ts`** (typed, still root-relative, no
  `schemaVersion`):
  - `listSkills` -> `GET skills`. Already superseded by `v2/skills`
    (E9-S1); **E16-S4** additionally folds it into the unified extension
    catalog.
  - `listAgents` -> `GET agents`. Already superseded by
    `v2/agents/catalog` (E9-S1); **E16-S4** adds create/edit and folds it
    into the unified catalog, which the legacy read-only endpoint never
    supported.
  - `getPlan` -> `GET plans/{sessionId}`. Gap closed by **E16-S2** (adds
    step-level approve/reject/execute-approved, which this legacy read-only
    endpoint has no equivalent for).
  - `generatePatch` -> `POST patches/generate`. Gap closed by **E16-S3**
    (adds changed-file listing, edited-content override, and a real
    apply/discard lifecycle; the legacy endpoint only diffs two inline
    strings and never touches the repository).

- **`frontend/lib/api_v2.ts`** (already versioned, `schemaVersion`-carrying,
  the pattern E16 extends rather than replaces):
  - `v2/sessions`, `v2/sessions/{id}/runs`: read/create surface for
    sessions and runs. **E16-S1** builds the chat/turn contract and
    timeline events on top of this, it does not replace it.
  - `v2/agents/catalog`, `v2/skills`, `v2/plugins/active`: read-only
    catalogs. **E16-S4** aggregates these three into one unified catalog
    endpoint and adds the write operations (enable/disable, agent
    create/edit) none of them currently has.
  - `v2/runs/{id}/events/stream` (SSE): the streaming transport **E16-S1**
    reuses for the extended event taxonomy — no new transport is
    introduced.
  - There is no `/v2` plan-approval surface, no `/v2` patch-review/apply
    surface, and no `/v2` provider-status surface today — **E16-S2**,
    **E16-S3**, and half of **E16-S4** start from zero on the `/v2` side
    even though their non-versioned analogues exist.

## Epic exit checklist

- [x] All 4 stories meet the global DoD (`../templates/dod_checklist.md`)
      plus their story-specific DoD above.
- [x] Contract tests green for the `/v2` chat/turn contract and extended
      event taxonomy (E16-S1), the plan approval state machine (E16-S2), the
      patch review/apply lifecycle (E16-S3), and the unified extension
      catalog plus provider config (E16-S4).
- [x] RFC-006 (additive-`/v2`-endpoints governance, covering the UI
      language/i18n decision for E15 and the API-contract decisions for
      E16) is approved before implementation starts on any of E16-S1..S4,
      per the project's RFC/ADR-before-implementation convention
      (`agent_guide.md` §5); an ADR is filed per story if its contract
      change is MAJOR. RFC-006 Accepted 2026-07-08; all four surfaces are
      additive within the `/v2` MAJOR (`schemaVersion` 2.0), so no per-story
      MAJOR ADR was required.
  - The RFC itself is authored by a sibling worker; this epic only
    depends on its approval, it does not produce it.
- [x] No story in this epic ships a Web UI change — that is E17's scope;
      this epic's DoD is satisfied purely by the `/v2` contracts, their
      tests, and their docs.
- [x] `docs/v2_platform/progress.md` updated with E16's status and story
      completion count.
- [x] The §18.9 wave-gate entry for the Beta wave is updated to reflect
      E16's four `/v2` surfaces as prerequisites for E17's Control Center
      screens.

## Implementation notes (2026-07-08)

The four `/v2` surfaces shipped as auto-discovered routers (no manual
registration): `chat_v2.py` (turns + `run.timeline.*` events + role map in
`api/timeline_roles.py`), `plan_approval_v2.py` (step state machine in
`plans/step_state.py` + `plan.step.*` events + `e16_s2_plan_state_machine.md`),
`patches_review_v2.py` (changed-files/diff/override/apply-discard reusing the E0
patch engine + `patch.changedfiles.listed`/`patch.discarded` events), and
`extensions_v2.py` + `provider_config_v2.py` (unified catalog + delegated
enable/disable + agent create/edit + provider status). The event catalog grew
append-only 20 → 31 types. Contract tests: S1 24, S2 15, S3 15, S4 (ext+provider)
cover each surface — all green.
