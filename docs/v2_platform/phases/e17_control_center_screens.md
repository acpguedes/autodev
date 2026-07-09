# E17 — Frontend Redesign: Control Center Screens

**Wave:** Beta
**Status:** Not started (0/6 complete)
**Depends on:** E15, E16
**Enables:** E14-S5
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.7.11

## Objective

Rebuild AutoDev Architect's user-facing screens on top of the new App Shell
(E15) and the enabled `/v2` control-plane endpoints (E16) so the Web UI
reproduces the "Execution Control Center" redesign prototype in
`layout_prototype_brainstorm/` — an editorial, chat-first execution view with
governed plan approval, patch review, session/config management, an
extensions hub, and a realigned visual flow editor, all wired to real
streaming and API data rather than static mockups.

## Key result

An operator drives an entire run — chat with an agent, review and approve a
plan, inspect and apply patches, manage sessions/config/extensions, and build
flows — through the redesigned screens, with no visual or interaction gap
against the prototype (`layout_prototype_brainstorm/Autodev Redesing.html`,
screenshots in `layout_prototype_brainstorm/Frontend redesign proposal.zip`
under `shots/`), each screen reading/writing exclusively through the E16
`/v2` endpoints (API-first, §2.13).

## Stories

### E17-S1 — Chat execution view

Subtasks:
- `E17-S1-T1`: editorial centered chat column — empty state with a serif
  headline and 4 task-suggestion cards; agent-role message stream rendering
  Planner/Coder/Validator role tags per message.
- `E17-S1-T2`: composer — auto-growing textarea, provider chip (shows active
  provider/model from E16-S4 config), `@context` mention affordance to
  attach files/sessions to the prompt.
- `E17-S1-T3`: live execution timeline in the right panel — status dots,
  spinners, and monospace step output across idle/running/done states, wired
  to E16-S1 with real SSE streaming (reusing the `RunEventStream` transport
  pattern).

| Item | Content |
| --- | --- |
| CF | Operator starts a chat from the empty state or a suggestion, sends a message, sees agent-role-tagged replies stream in, and watches the run's steps update live in the timeline panel |
| CNF | WCAG 2.2 AA contrast/focus; keyboard-navigable composer and timeline; streaming consumption < 1 s (inherited from E9-S2); Storybook coverage for message, timeline-step, and composer components |
| DoR | E16-S1 (`/v2` chat + timeline endpoints) available; E15-S2 (control-center shell) ready; prototype chat view and `shots/` screenshots reviewed |
| DoD | Storybook stories for message/timeline/composer states; a11y audit; e2e test of send-message-to-streamed-reply; screen docs |
| Dependencies | E16-S1, E15-S2 |

Origin: E10-S2, E9-S2.

### E17-S2 — Plans screen with approval gates

Subtasks:
- `E17-S2-T1`: stat cards summarizing step count, approved-step count, and
  file impact for the active plan.
- `E17-S2-T2`: step cards with inline title/description editing and
  approve/reject status pills per step; add/remove-step affordances.
- `E17-S2-T3`: "execute approved plan" sticky footer, enabled once at least
  one step is approved, wired to E16-S2's plan-approval endpoints.

| Item | Content |
| --- | --- |
| CF | Operator edits a step inline, toggles approve/reject, adds/removes steps, and triggers execution once ≥1 step is approved, all reflected via E16-S2 |
| CNF | WCAG 2.2 AA; keyboard-operable status pills and footer action; Storybook coverage for stat card, step card, and status pill |
| DoR | E16-S2 (plan approval-gate endpoints) available; E15-S2 ready; prototype plans view and `shots/` screenshots reviewed |
| DoD | Storybook stories; a11y audit; e2e test of edit → approve → execute; screen docs |
| Dependencies | E16-S2, E15-S2 |

Origin: E10-S2, E3.

#### Implementation notes (E17-S2)

- **Endpoint wiring.** The screen reads/writes exclusively through the E16-S2
  `/v2/plans` control-plane endpoints via the typed client
  `frontend/lib/plans_v2.ts`: `GET /v2/plans/{sessionId}` (`getPlanV2`) loads
  the plan; `PUT .../steps/{stepIndex}` (`updatePlanStepV2`) saves inline
  title/description edits; `POST .../steps/{stepIndex}/approve` and
  `.../reject` (`approvePlanStepV2` / `rejectPlanStepV2`) toggle the approval
  gate; `POST .../steps` (`addPlanStepV2`) and `DELETE .../steps/{stepIndex}`
  (`removePlanStepV2`) manage steps; and `POST .../execute-approved`
  (`executeApprovedStepsV2`) drives the sticky footer. No screen state exists
  that is not derived from a `/v2` response.
- **Session selection.** Plans are keyed by session, so the screen starts
  with a session-ID input and loads the plan on submit — there is no
  "current session" ambient state in the shell yet, keeping the screen
  self-contained and directly deep-linkable later.
- **Step-state gating.** Which steps are editable/removable is centralized in
  `EDITABLE_STEP_STATES` / `REMOVABLE_STEP_STATES`
  (`ReadonlySet<PlanStepState>` in `frontend/lib/plans_v2.ts`) rather than
  scattered per-component conditionals, so backend state-machine changes only
  need a one-place update.
- **Components.** `StatCard` (step count / approved count / file impact),
  `StepCard` (inline title/description edit + approve/reject pills + remove),
  `StepStatusBadge`, and `ExecuteApprovedFooter` (enabled once ≥1 step is
  approved) each ship a Storybook story alongside the component under
  `frontend/components/plans/`.
- **Per-step busy tracking.** Mutations track in-flight state per step index
  (`stepBusy: Record<number, boolean>`); successful removals delete the
  entry outright (`clearBusy`) instead of leaving a stale `true` entry behind
  the shifted indices.
- **E2E strategy.** `frontend/e2e/plans-approval-gates.spec.ts` intercepts
  `**/v2/plans/**` with Playwright's `page.route()` and serves a stateful
  in-memory plan fixture (mirroring `sessions-config.spec.ts` /
  `shell-navigation.spec.ts`), covering load, inline edit, approve, reject,
  add step, remove step, and execute-approved — fast and non-flaky, with no
  seeded backend required.

### E17-S3 — Patches review screen

Subtasks:
- `E17-S3-T1`: left file panel listing changed files with per-file +/− line
  counts.
- `E17-S3-T2`: right segmented Diff/Edit viewer — unified diff with line
  numbers and add/del gutters, a dry-run badge, and a monospace editor whose
  manual edits fold back into the applied patch.
- `E17-S3-T3`: apply-approved and discard actions, wired to E16-S3's patch
  review/apply endpoints.

| Item | Content |
| --- | --- |
| CF | Operator selects a file, reviews its unified diff or switches to Edit mode, edits inline, and applies or discards the patch via E16-S3, with a visible dry-run indicator before apply |
| CNF | WCAG 2.2 AA; keyboard navigation across file list and diff/edit segments; before/after diff never lost on segment switch; Storybook coverage for file-panel row, diff gutter, and segmented control |
| DoR | E16-S3 (patches review/apply endpoints) available; E15-S2 ready; prototype patches view and `shots/` screenshots reviewed |
| DoD | Storybook stories; a11y audit; e2e test of diff-view → edit → apply; screen docs |
| Dependencies | E16-S3, E15-S2 |

Origin: E10-S2, E0.

### E17-S4 — Sessions & Config screens

Subtasks:
- `E17-S4-T1`: session list on `/v2` sessions — goal, session ID, run count,
  relative time, a status glow dot (running/done/failed), and a
  reopen-session-as-chat action back into E17-S1.
- `E17-S4-T2`: provider/config screen — Stub offline / Ollama / OpenAI
  provider selector, model, base URL, project directory, and default goal
  fields, wired to E16-S4.
- `E17-S4-T3`: form validation and optimistic status feedback on save.

| Item | Content |
| --- | --- |
| CF | Operator browses sessions with live status glow, reopens one as a chat, and edits/saves provider config, all reflected via E16-S4 |
| CNF | WCAG 2.2 AA; glow-dot states also conveyed non-visually (text/label) for color-blind and screen-reader users; Storybook coverage for session-row and config-form fields |
| DoR | E16-S4 (extensions + provider config endpoints) available; E15-S2 ready; prototype sessions/config views and `shots/` screenshots reviewed |
| DoD | Storybook stories; a11y audit; e2e test of reopen-session and save-config; screen docs |
| Dependencies | E16-S4, E15-S2 |

Origin: E10-S2, E8-S1, E5.

#### Implementation notes (E17-S4)

- **Endpoint wiring.** The config screen reads/writes the entire provider +
  repository form through the two E16-S4 endpoints already exposed by
  `backend/api/routers/config_v2.py` and
  `backend/api/routers/provider_config_v2.py`: `GET/PUT /v2/config`
  (`getRuntimeConfigV2` / `updateRuntimeConfigV2` in `frontend/lib/api_v2.ts`)
  covers the full form (provider, model, base URL, temperature, API key,
  repository label, project directory, default goal) in one round trip, and
  `GET /v2/provider-config/status` (`getProviderStatusV2`) supplies the live
  healthy/configured badge shown in both the config screen and the shell's
  sidebar provider card. No separate PUT-per-field endpoint was needed.
- **Reopen-as-chat contract.** `SessionRow`'s "Open chat" action links to
  `/?sessionId=<sessionId>` (query param name `sessionId`, URI-encoded). This
  is the exact contract E17-S1's chat screen depends on to resume an existing
  session instead of starting a new one — the session's **goal** cell links
  elsewhere, to `/sessions/<sessionId>` (this story's own detail screen), so
  the two links intentionally target different routes.
- **Repository-intelligence panel dropped.** The prototype sketches hint at a
  repository-intelligence side panel on the config screen, but no
  `/v2/repository` (or equivalent) endpoint exists yet in E16. Per the
  API-first rule, that panel was left out of this story rather than backed by
  a stub; it can be added once a corresponding `/v2` endpoint lands.
- **E2E strategy.** `frontend/e2e/sessions-config.spec.ts` intercepts
  `http://localhost:8000/v2/**` with Playwright's `page.route()` and serves
  deterministic fixtures, rather than depending on a live/seeded backend —
  this satisfies the "assert real rendered state" DoD while keeping the spec
  fast and non-flaky. It runs alongside the pre-existing
  `frontend/e2e/shell-navigation.spec.ts`, which already covers `/sessions`
  and `/config` inside the three-region shell.
- **Integration gap (S1↔S4).** The reopen-as-chat link emitted by `SessionRow.tsx`
  (`/?sessionId=<id>`) is not yet consumed by E17-S1's `frontend/app/page.tsx`;
  that screen needs `useSearchParams`/`sessionId` handling to resume the session
  and complete the end-to-end flow. To be resolved at epic merge or as a fast-follow.

### E17-S5 — Extensions hub screen

Subtasks:
- `E17-S5-T1`: tabbed layout — Agents / Skills / Plugins / MCP, each tab
  label showing a live item count.
- `E17-S5-T2`: item cards — name, manifest/version, description,
  active/inactive status pill, enable/disable toggle, click-to-edit.
- `E17-S5-T3`: create/install modal with per-type forms, including an agent
  form (system prompt, model, allowed tools), wired to E16-S4.

| Item | Content |
| --- | --- |
| CF | Operator switches tabs, toggles an item's active state, edits an item, and creates/installs a new agent/skill/plugin/MCP entry via the modal, all reflected via E16-S4 |
| CNF | WCAG 2.2 AA; keyboard-operable tabs, toggles, and modal (focus trap, Escape to close); Storybook coverage for tab bar, item card, and modal forms |
| DoR | E16-S4 available; E15-S2 ready; prototype extensions-hub view and `shots/` screenshots reviewed |
| DoD | Storybook stories; a11y audit; e2e test of toggle + create-via-modal; screen docs |
| Dependencies | E16-S4, E15-S2 |

Origin: E10-S2, E1/E2/E6/E9-S4.

### E17-S6 — Flow builder alignment

Subtasks:
- `E17-S6-T1`: realign the existing `frontend/components/flow/` editor
  (`FlowCanvas.tsx`, `FlowEditor.tsx`, `NodeInspector.tsx`,
  `ValidationPanel.tsx`) inside the new control-center shell.
- `E17-S6-T2`: palette sections — flows library, the 8 agent types, and
  control blocks (prompt-step, condition, loop, human approval, parallel,
  start/end); draggable nodes on a dotted grid; curved edges with branch
  labels.
- `E17-S6-T3`: right inspector with type-specific fields per node kind; save
  action exports `flow.yaml` and shows a confirmation toast.

| Item | Content |
| --- | --- |
| CF | Operator drags a palette node onto the canvas, connects it with a labeled branch edge, edits its type-specific fields in the inspector, and saves — producing a valid `flow.yaml` with a toast confirmation |
| CNF | WCAG 2.2 AA; canvas keyboard-operable (node focus/move, edge creation) per the existing E10-S3 baseline; round-trip with `flow.yaml` remains lossless; Storybook coverage for palette sections and inspector field types |
| DoR | E10-S3 visual flow editor (existing baseline) reviewed; E15-S2 ready; prototype flow-builder view and `shots/` screenshots reviewed |
| DoD | Round-trip test preserved; a11y audit; e2e test of drag-connect-save; screen docs |
| Dependencies | E15-S2 |

Origin: E10-S3, E3-S6.

## v1 precursor / starting point

The current Next.js App Router UI (`frontend/app/`) already has 9 routes:
`/` (chat/home), `/sessions`, `/sessions/[sessionId]`, `/config`, `/agents`,
`/skills`, `/plans`, `/patches`, `/flows`, plus the pluggable-panel host at
`/panels` (E10-S4). It runs on plain CSS with no component library (E10's
starting point) and predates the redesign entirely — none of these routes
reproduce the prototype's editorial layout, role-tagged chat, or approval-gate
interactions. E17 does not add new routes; it re-implements the screens each
existing route already serves, inside the new shell (E15) and against the new
`/v2` endpoints (E16). Mapping from today's screens to the prototype's 7
views:

- `/` -> **Chat execution view** (E17-S1). Today: a minimal landing/dispatch
  page with no agent-role stream, no live timeline, and no `@context`
  affordance.
- `/plans` -> **Plans screen with approval gates** (E17-S2). Today: a flat
  step list with no stat cards, no inline editing, and no approval-gate
  footer gating execution.
- `/patches` -> **Patches review screen** (E17-S3). Today: a basic diff
  listing with no file +/− counts, no Diff/Edit segmented viewer, and no
  dry-run badge.
- `/sessions` and `/sessions/[sessionId]` -> **Sessions screen** (E17-S4,
  session half). Today: session data exists and `RunEventStream.tsx`
  (`frontend/components/RunEventStream.tsx`) already streams run/step events
  into the session detail page, but there is no status glow dot, no
  reopen-as-chat action, and no unified session list matching the prototype.
- `/config` -> **Config screen** (E17-S4, config half). Today: a config form
  exists but is unstyled relative to the prototype and not yet wired to the
  E16-S4 `/v2` provider/config endpoints.
- `/agents`, `/skills` (and the absence of dedicated Plugins/MCP screens) ->
  **Extensions hub screen** (E17-S5). Today: agents and skills each have a
  separate, differently-styled catalog page; there is no unified tabbed hub
  with live counts, and no create/install modal.
- `/flows` and `frontend/components/flow/` (`FlowCanvas.tsx`,
  `FlowEditor.tsx`, `NodeInspector.tsx`, `ValidationPanel.tsx`) ->
  **Flow builder** (E17-S6). Today: a functional visual editor already exists
  from E10-S3 (graph canvas, `flow.yaml` round-trip, validation panel), but
  its palette, node styling, and inspector predate the redesign and need
  realignment rather than a rebuild.
- `/panels` (E10-S4 pluggable panel host) has no direct prototype
  counterpart; it is out of scope for E17 and is expected to be re-themed
  under the new shell by E15 rather than rebuilt here.

## Epic exit checklist

- [ ] All 6 stories meet the global DoD (`../templates/dod_checklist.md`)
      plus their story-specific DoD above.
- [ ] Every screen matches the prototype (`layout_prototype_brainstorm/Autodev
      Redesing.html`, `shots/` inside `layout_prototype_brainstorm/Frontend
      redesign proposal.zip`) with no blocking visual or interaction gap.
- [ ] Contract tests green for each screen's E16 API wiring (no direct State
      Store access from any `frontend/` screen, per §2.13).
- [ ] a11y audit passes with no blocking WCAG 2.2 AA violations across all 6
      screens; Storybook coverage published for new/realigned components.
- [ ] UI language decision (English default + pt-BR via i18n, RFC-006)
      applied consistently across all 6 screens.
- [ ] `docs/v2_platform/progress.md` updated.
- [ ] §18.9 Beta wave-gate entry for the frontend redesign satisfied.
