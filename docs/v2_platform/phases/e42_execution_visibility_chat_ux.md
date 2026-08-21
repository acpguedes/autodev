# E42 — Execution Visibility & Chat/Command UX

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/6
**Depends on:** E41 (the execution path this epic makes visible/usable),
E9 (event catalog/bus), E11 (auth/scopes), E15-E18 (frontend foundation)
**Enables:** a genuinely usable Beta UX for the primary Chat-driven flow —
today the platform can write real code (E41) but the UI that's supposed to
show that happening is either broken (404/403) or hard to read
**Canonical source:** direct manual test of the full local stack (backend +
frontend) against a real OpenAI key, 2026-08-21 — a "Build a simple payment
API" goal run end to end through the Chat UI's Run plan button, which
correctly wrote a complete, working project (verified: 4/4 generated tests
pass), while the Execution/Plans pages and server log surfaced the three
bugs below.

## Objective

E41 closed the gap where the platform couldn't turn a goal into real code.
Running that fixed pipeline through the actual product UI (not just the
CLI) surfaced a second, distinct gap: the UI built to let a human watch and
work with that execution has real, load-bearing defects, plus a set of
UX gaps that make it hard to use even when the data is correct. This epic
fixes both.

Three defects were root-caused directly (not just observed):

1. **`GET /v2/runs/{run_id}/events/stream` 404s for every Chat-triggered
   run.** The route exists and is correctly registered (confirmed via
   `/openapi.json`) but `runs_stream_v2.py` resolves `run_id` against the
   **Flow Engine's** run store (`engine.runs.get_run(...)`). Runs started
   from Chat go through the **Orchestrator's** session/run store instead —
   a completely different system. The two execution paths (visual Flows vs.
   Chat) were never unified under one event stream, so the Execution side
   panel can never show real-time progress for the path most users actually
   use.
2. **`GET /v2/execution/policy/dynamic` 403s under the local zero-config
   dev principal** ("Could not load pending decisions" on the Execution
   page). The route requires `@requires_scope("policy:read")`; the local
   `Role.OWNER` principal's effective scopes apparently don't include it —
   a real local-dev role/scope gap, not a routing issue.
3. **Plans page never shows a plan** the user just generated — it requires
   manually pasting a session ID (`Enter a session id to load its plan`)
   instead of defaulting to the session already active in Chat.

## Key result

A user runs a goal from Chat and can, without leaving the browser or typing
any IDs by hand: watch the plan/analysis/patch/validation timeline update in
real time, see live command stdout/stderr as validation runs, and read the
conversation in a layout that actually looks like a chat.

## Stories

### E42-S1 — Unify run-event streaming across Flow and Orchestrator paths — **Not started**

Fix the root cause of the 404. `run.timeline.*` events need one consistent
source of truth reachable by `run_id` regardless of whether the run was
started by the Flow Engine or the Orchestrator.

Subtasks:
- `E42-S1-T1`: decide and document the unification approach — either (a)
  `stream_run_events` checks both stores, trying Flow Engine then
  Orchestrator, or (b) Orchestrator runs publish onto the same event
  bus/catalog contract the Flow Engine already uses, so a single lookup
  works for both. Recommend (b): it keeps one source of truth instead of
  two lookup paths that can drift again.
- `E42-S1-T2`: implement the chosen approach; `run_id`s from either system
  resolve correctly.
- `E42-S1-T3`: regression test: start a run via `POST /v2/sessions/{id}/turns`
  (Chat path) and assert `GET /v2/runs/{run_id}/events/stream` returns a
  real stream, not 404.

| Criterion | Detail |
| --- | --- |
| Functional | A Chat-triggered run's `run_id` resolves on `/v2/runs/{run_id}/events/stream`; a Flow-triggered run continues to work unchanged |
| Non-functional | No duplicate event publication for Flow runs (avoid double-counting if both paths end up feeding the same bus) |
| DoR (specific) | E41 landed (real runs to observe exist) |
| DoD (specific) | Contract test per execution path asserting stream resolution |
| Dependencies | E41, E9 (event bus contract) |

### E42-S2 — Close the local-dev role/scope gap on Execution endpoints — **Not started**

Subtasks:
- `E42-S2-T1`: audit every `@requires_scope(...)`-gated `/v2/execution/*`
  and `/v2/runs/*` endpoint against `Role.OWNER`'s effective scopes
  (`backend/auth/service.py`'s local zero-config grant); list every gap,
  not just `policy:read`.
- `E42-S2-T2`: close the gaps found — `Role.OWNER` should have every scope
  it needs for a fully local, zero-config session to use every page without
  a 403.
- `E42-S2-T3`: regression test asserting the local dev principal can call
  every Execution-page-backing endpoint successfully.

| Criterion | Detail |
| --- | --- |
| Functional | `/v2/execution/policy/dynamic` and every other audited endpoint return 200 for the local `Role.OWNER` principal |
| Non-functional | No scope widening for non-local/multi-tenant principals — this only fixes the local zero-config grant |
| DoR (specific) | E42-S2-T1's audit complete |
| DoD (specific) | Test enumerating audited endpoints against `Role.OWNER` |
| Dependencies | E11 (auth/scopes) |

### E42-S3 — Default Plans/Execution pages to the active session — **Not started**

Subtasks:
- `E42-S3-T1`: Plans and Execution pages read the currently-active session
  (already known to Chat/session state) instead of requiring a pasted
  session ID; manual entry remains available for inspecting a different
  session.
- `E42-S3-T2`: when no session is active, show an explicit empty state
  ("start a session in Chat first") instead of a bare input box.

| Criterion | Detail |
| --- | --- |
| Functional | Navigating to Plans/Execution right after a Chat run shows that run's data with no manual ID entry |
| Non-functional | Manually loading a different session ID still works |
| DoR (specific) | none beyond existing session-state plumbing |
| DoD (specific) | Manual verification: Chat → Run plan → Plans/Execution show data unprompted |
| Dependencies | E42-S1 (Execution page also needs the stream fix to show live data, not just historical) |

### E42-S4 — Chat layout: real chat bubbles + collapsible turns — **Not started**

Subtasks:
- `E42-S4-T1`: user messages right-aligned with a distinct background
  color; agent/persona messages left-aligned — standard two-sided chat
  layout instead of a uniform left-aligned list.
- `E42-S4-T2`: each turn (user or agent) is collapsible/expandable, closed
  by default once a turn's content exceeds a reasonable length, so a long
  coder/analyzer turn doesn't dominate the scroll.
- `E42-S4-T3`: fix the reported vertical-scroll-constrained content boxes —
  audit nested scroll containers across Chat/Execution/Plans for the
  specific CSS/layout cause (likely a fixed-height container fighting its
  own overflow content) rather than only patching the symptom in Chat.

| Criterion | Detail |
| --- | --- |
| Functional | User/agent turns are visually distinguishable at a glance; any turn can be collapsed; page scroll reaches all content on every affected page |
| Non-functional | No regression to existing Chat streaming/update behavior |
| DoR (specific) | none |
| DoD (specific) | Visual/manual verification across Chat, Execution, Plans |
| Dependencies | none |

### E42-S5 — Live command execution panel (stdout/stderr) — **Not started**

Subtasks:
- `E42-S5-T1`: a panel (Execution page, and/or inline in Chat) that streams
  a running validation/devops command's stdout/stderr live, sourced from
  the same `ExecutionResult.stdout`/`.stderr` data already recorded per
  action (confirmed present and populated during E41 testing) — pushed via
  the unified event stream from E42-S1.
- `E42-S5-T2`: read-only by design for this story — a live *view* of
  command output, not an interactive terminal a user can type into.
  Recommendation, not a decision to implement here: a real interactive
  terminal (commands typed by the user, piped to the same sandboxed
  execution backend) is a materially bigger, security-sensitive scope
  (arbitrary command execution from the browser) and should be its own
  future story/epic if wanted, not bundled into this read-only view.
- `E42-S5-T3`: scrollback retained per run (at least for the run's
  lifetime) so a user can review output after a command finishes, not only
  while it's streaming.

| Criterion | Detail |
| --- | --- |
| Functional | Running "Run plan" with a validation command in the plan shows that command's real stdout/stderr appearing live, not just a final status |
| Non-functional | No new execution surface — this only visualizes output the sandbox already produces (E32/E41) |
| DoR (specific) | E42-S1 (needs a working live stream to push into) |
| DoD (specific) | Manual verification: trigger a run with a validation command, observe live output |
| Dependencies | E42-S1, E41-S4 (agent-directed commands) |

### E42-S6 — Flow editor canvas space — **Not started**

Subtasks:
- `E42-S6-T1`: give the visual flow editor canvas more usable screen space
  (larger default viewport, less competing chrome, or a collapsible side
  panel) so a flow graph is legible without excessive panning/zooming.

| Criterion | Detail |
| --- | --- |
| Functional | A flow with several connected nodes (e.g. the existing `autodev/flow-feature-delivery` sample) is readable without manual resizing on a standard laptop viewport |
| Non-functional | No change to flow editing/save behavior |
| DoR (specific) | none |
| DoD (specific) | Visual/manual verification |
| Dependencies | none |

## Contracts & decisions

- No new extension point. E42-S1's recommended approach (unify onto the
  existing event bus/catalog contract) reuses E9's event infrastructure
  rather than inventing a second run-tracking mechanism.
- E42-S5 deliberately scopes out an interactive browser terminal — noted as
  a explicit non-goal for this epic, not silently dropped.

## DoR / DoD

- **DoR:** E41 landed (there must be real Chat-driven runs to make visible);
  E42-S2-T1's scope audit complete before S2 implementation starts.
- **DoD:** all story DoDs met; a full Chat → Run plan → live
  plan/analysis/patch/validation timeline + live command output rehearsal
  works without manual session-ID entry or a 403/404 anywhere in the path;
  `docs/v2_platform/progress.md` updated; no push/PR without explicit
  authorization.
