# E43 — Execution Transparency: Terminal Transcript, File Browser & Session Stickiness

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35, E41, and E42: added after initial Beta
completion, before the wave is signed off).
**Status:** Complete · **Stories:** 7/7 (E43-S6/S7 added post-completion, found via the user's own manual verification of E43-S1..S5)
**Depends on:** E42 (specifically E42-S1's event stream and E42-S3's
active-session concept — both real and reused here, not rebuilt), E41-S3
(patch-apply actions), E41-S4 (agent-directed commands), E41-S5
(self-verification retry loop — currently defeated by this epic's S1)
**Enables:** genuine transparency into what the platform did to a project,
and validation that can actually succeed — today a user can see that
something ran, but not read it the way they would read their own terminal,
and validation itself cannot pass regardless of code correctness
**Canonical source:** direct manual re-test of E42 in the actual product UI,
2026-08-21 — the Execution panel and session Live stream tab both work and
stream real events (E42-S1 confirmed delivered), but what's rendered is raw
JSON event payloads, not the human-readable command/output view E42-S5 was
meant to produce. User feedback, verbatim intent: the side panel should
"literally look like a command being called in bash and its output," show
which command was used to write a file, show step-level annotations like
"creating main.py," have a file-tree browser for the project, let files be
read directly in the frontend, and every screen should default to the most
recently selected session, not just Plans/Execution.

**Confirmed at total-failure severity, not just partial:** the full Chat
transcript for one run showed tasks 1-36 (planning/analysis/architecture/
implementation/operations) all `Completed`, then **every single one** of
tasks 37-46 — the entire validation phase, 10/10 tasks — `Failed`. Each one
was a different command (`test -f main.py ...`, `python -m venv .venv`,
`pip install -r requirements.txt`, `compileall main.py`, pytest-equivalent
inline scripts, a live `uvicorn` smoke test, a `grep` check on `README.md`)
but every one was prefixed `cd /path/to/project && ...`, and every one
failed with "Command 'cd' is not in the allowed list." This is not an edge
case E43-S1's transcript rendering will occasionally surface — with the
validator agent's natural `cd <dir> && <command>` habit, it is currently
**the only outcome validation can ever have**, regardless of whether the
generated code is correct.

## Objective

E41 closed the gap where the platform couldn't turn a goal into real code.
Testing that pipeline through the actual product UI surfaced two further,
distinct gaps this epic closes: (1) validation cannot currently pass at
all, for any goal, because of a sandbox command-parsing limitation; (2) the
UI built to let a human watch and work with an execution has real defects
and missing capabilities on top of that.

## Key result

Watching a run in the browser reads like watching your own terminal: each
action appears as a command line with its real output (a patch-apply shows
what file it wrote and a summary of the change; a validation command shows
its real stdout/stderr — and actually has a chance to pass), each step
carries a plain-language label like "Creating main.py," the project's file
tree is browsable and every file readable in-app, and navigating to any
page (Chat, Plans, Execution, Patches) shows the session you were just
looking at by default.

## Stories

### E43-S1 — Fix sandboxed execution for `cd`-prefixed commands — **Complete**

The blocking correctness fix. `backend/validation/sandbox.py`'s allowlist
check inspects only a command's first token against a fixed executable set
(`pytest`, `ruff`, `npm`, `python`, `python3`). Agent-declared commands
naturally arrive as `cd <project_dir> && <real command>` — `cd` is a shell
builtin, never a matchable executable, so every such command is rejected
before the real command it's chaining to is ever inspected.

Subtasks:
- `E43-S1-T1`: give the sandbox runner an explicit working-directory
  parameter (it already knows the run's workspace root from E32) so agents
  don't need to `cd` at all — commands run with `cwd` set correctly,
  no shell chaining required.
- `E43-S1-T2`: for compound commands that still arrive as `cd X && Y`
  (defense in depth — prompts can't be perfectly constrained), parse and
  strip a leading `cd <path> &&`/`cd <path>;` segment, verify `<path>`
  resolves inside the guarded workspace root (same containment check
  `apply_patch` already uses), and evaluate the allowlist against the
  *real* command that follows, not `cd`.
- `E43-S1-T3`: regression test reproducing the exact failure mode found
  live — a `cd <dir> && pytest`-style command must now execute `pytest`
  (allowlisted) inside `<dir>`, not fail on `cd`.
- `E43-S1-T4`: once fixed, re-run E41-S5's self-verification loop against a
  goal whose first attempt is deliberately broken, and confirm the retry
  loop can now actually observe a real pass/fail instead of an
  unconditional environment-level failure.

| Criterion | Detail |
| --- | --- |
| Functional | A `cd <workspace-relative-or-absolute-dir> && pytest`-style agent-declared command executes `pytest` inside that directory and reports its real result, not a "not in the allowed list" rejection |
| Non-functional | The path-containment check on the `cd` target is at least as strict as `apply_patch`'s existing guard — no new traversal surface |
| DoR (specific) | none — root cause already isolated to `backend/validation/sandbox.py` |
| DoD (specific) | Regression test per T3; E41-S5's retry loop test (T4) passes end to end |
| Dependencies | E32 (workspace root), E41-S4, E41-S5 |

### E43-S2 — Terminal-style transcript rendering (supersedes E42-S5's raw JSON view) — **Complete**

**Two separate rendering surfaces need this fix, not one** — confirmed by
inspecting both directly, not assumed:

1. **Sessions → session detail → Live stream tab** renders each SSE event
   as its raw JSON payload verbatim. This is the surface E42-S5 was
   supposed to fix and didn't.
2. **Chat's own "Execution" side panel** is *already* semi-structured —
   each entry has a `code` label (e.g. `validation: Run cd ... &&
   test -f main.py ...`) and a `pre` block beneath it, not raw JSON. But
   it still doesn't solve the actual problem: for every failed validation
   entry observed, the `pre` block just repeats "Run agent-declared
   command: cd ...&&..." — the same text as the label — never the real
   failure reason (`Command 'cd' is not in the allowed list.`) or any real
   stdout/stderr. There is no observed evidence this panel ever renders a
   *successful* command's real output; it may only ever echo the command
   itself today.

Subtasks:
- `E43-S2-T1`: a transcript renderer that consumes the same
  `run.timeline.*`/`execution.*` SSE events E42-S1 already streams and
  turns each into one terminal-style line — a synthetic command prompt plus
  real output — rather than displaying the event's JSON payload directly.
  Applies to **both** surfaces above, as one shared renderer, not two
  independent implementations that can drift again.
- `E43-S2-T2`: patch-apply actions (E41-S3) render as a write command (e.g.
  a `$ write main.py` style line) followed by a concise summary of what
  changed (not necessarily the full diff inline — link/expand to it), so
  "which command was used to write a file" is answered directly instead of
  requiring the user to parse a `PatchResult.message` string out of JSON.
- `E43-S2-T3`: real validation/devops commands (E41-S4, now actually able to
  pass per E43-S1) render as an actual `$ pytest` (etc.) line with real
  stdout/stderr streamed beneath it as it arrives — not only a final
  status, and not the command text echoed back as if it were the output.
- `E43-S2-T4`: replace the raw-JSON Live-stream tab content, and the
  command-echoing Chat Execution panel content, with this same shared
  renderer; a "view raw event" toggle may remain available for debugging,
  but is not the default in either surface.

| Criterion | Detail |
| --- | --- |
| Functional | Every patch-apply and command action in a run appears as a readable terminal-style line with its real output, in chronological order, with no JSON and no command-echoed-as-output visible by default, **in both the session Live stream tab and Chat's Execution panel** |
| Non-functional | No new backend surface — this is a rendering layer over E42-S1's existing stream, shared by both surfaces |
| DoR (specific) | E42-S1 landed (confirmed working) |
| DoD (specific) | Manual verification in both surfaces: trigger a run with both a patch-apply and a validation command, observe both rendered as transcript lines with real output, not echoed commands |
| Dependencies | E42-S1, E41-S3, E41-S4, E43-S1 (so there's a real passing command to render, not only failures) |

### E43-S3 — Step-level plain-language annotations — **Complete**

Subtasks:
- `E43-S3-T1`: surface each task's human-readable title/description (already
  present in execution metadata, e.g. "Implement Main Application File") as
  a small label/header above its transcript entry — "Creating `main.py`"
  rather than a bare `task_id` like `coding-file-1`.
- `E43-S3-T2`: apply the same treatment to non-file steps (planning,
  analysis, validation) so the whole transcript reads as a narrated
  sequence, not just the file-writing steps.

| Criterion | Detail |
| --- | --- |
| Functional | Every transcript entry from E43-S2 carries a plain-language label derived from its task metadata, not a raw task/step ID |
| Non-functional | Falls back gracefully (shows the raw id) when a task genuinely has no description |
| DoR (specific) | E43-S2 landed |
| DoD (specific) | Manual verification across planning/analysis/patch/validation entries |
| Dependencies | E43-S2 |

### E43-S4 — Project file tree browser + in-app file viewer — **Complete**

A new capability — no existing endpoint lists a project's file tree or
serves raw file content scoped to `project_root`; the closest existing
thing (`/v2/repository/context`) is ranked RAG context, not a browsable
tree.

Subtasks:
- `E43-S4-T1`: new read-only backend endpoint(s) to list the active
  session's `project_root` as a file tree and to fetch one file's raw
  content by relative path — guarded by the same root-containment check
  already proven in `backend.patches.engine.apply_patch` (reject anything
  resolving outside `project_root`), applied here to reads instead of
  writes.
- `E43-S4-T2`: a file-tree panel (sidebar or dedicated tab) driven by that
  endpoint, showing the generated project's actual structure.
- `E43-S4-T3`: clicking a file opens its content in-app (read-only viewer,
  syntax-highlighted where reasonable) — no download/external-editor
  round-trip required to see what the platform wrote.

| Criterion | Detail |
| --- | --- |
| Functional | A user can browse the active session's project tree and read any file's current content without leaving the browser |
| Non-functional | Read-only; the traversal guard rejects any path escaping `project_root`, mirroring the existing patch-apply guard |
| DoR (specific) | none beyond an active session with a resolved `project_root` |
| DoD (specific) | Test asserting the path-traversal guard rejects an escaping path, mirroring `apply_patch`'s existing test |
| Dependencies | E41 (project_root resolution) |

### E43-S5 — App-wide session stickiness — **Complete**

Broadens E42-S3 (which only fixed Plans/Execution) to every page.

Subtasks:
- `E43-S5-T1`: a single shared "active session" concept read by every page
  — Chat, Plans, Execution, Patches, and E43-S4's new file browser —
  instead of each page independently deciding its own default (or none).
- `E43-S5-T2`: selecting/creating a session anywhere in the app updates
  this shared state; navigating to any other page reflects that session
  immediately, with manual override (pick a different session) still
  available everywhere.

| Criterion | Detail |
| --- | --- |
| Functional | Selecting a session in Sessions or Chat, then navigating to Plans/Execution/Patches/the new file browser, shows that same session with no re-selection |
| Non-functional | No change to the ability to explicitly view a different session |
| DoR (specific) | E42-S3 landed (this generalizes it) |
| DoD (specific) | Manual verification: select a session, visit every page, confirm consistency |
| Dependencies | E42-S3 |

### E43-S6 — Asynchronous turn creation (live execution visibility while a turn runs) — **Complete**

Found via the user's own manual verification of E43-S1..S5 in the actual
product UI (2026-08-21): sending a Chat message showed "Sending..."
indefinitely, the composer never cleared, and the Execution panel showed
nothing until navigating away (to Sessions) and back forced a fresh
re-fetch — by which point the turn had actually finished. Root cause:
`POST /v2/sessions/{id}/turns` ran the *entire* 7-agent pipeline
synchronously inside one HTTP request (`OrchestratorService.handle_message`
→ `self._graph.invoke(...)`), so the frontend had no `run_id` to open its
live `run.timeline.*`/`execution.action.*` subscription against until the
response arrived — by which point there was nothing left to stream. Not a
gap in E43-S2/S3's rendering (confirmed correct); the run_id itself never
reached the browser early enough to be useful.

Subtasks:
- `E43-S6-T1`: `OrchestratorService.begin_message` — admits the run
  (session lookup, run-type inference, concurrency-lease acquisition, the
  initial `RunStatus.RUNNING` row, and the `flow.run.started` event that
  creates the run's `EventStore` projection) synchronously, then runs the
  agent graph in a background job via the existing `backend.jobs.queue`
  infrastructure (reused as-is; not a new subsystem) and returns
  immediately. `handle_message` itself is unchanged — the CLI, the frozen
  v1 `/chat`, and `backend/api/routers/orchestration.py` all still call it
  and still block synchronously, by design.
- `E43-S6-T2`: `POST /v2/sessions/{id}/turns` (`chat_v2.py`) calls
  `begin_message` instead. `GET /v2/turns/{id}` (unchanged) becomes the
  poll target for the real, completed result.
- `E43-S6-T3`: added `RunStatus.FAILED` — previously a graph exception left
  the run row stuck at `running` forever (no `except` around the graph
  invoke; always had an HTTP caller to surface a 500 to instead). The
  background job now catches, persists `FAILED` with the error recorded,
  and releases the lease either way.
- `E43-S6-T4`: `frontend/app/page.tsx`'s `handleSubmit` sets the active
  turn immediately (unblocking the Execution panel's live subscription),
  polls `GET /v2/turns/{id}` to completion, and clears the composer on
  submit rather than on completion.
- `E43-S6-T5`: discovered while testing — `backend/cli_shell.py`'s
  `run_goal` also assumed synchronous turn completion (calling
  `execute()` immediately after `create_turn()`, deriving the execution
  plan from artifacts the now-backgrounded pipeline hadn't produced yet,
  400ing). Added `ShellSession.wait_for_turn` (poll `GET /v2/turns/{id}`,
  API-only, no `backend.*` imports per this module's own contract) and
  call it between `create_turn`/`execute`.

| Criterion | Detail |
| --- | --- |
| Functional | Sending a Chat message shows the Execution panel populate live (via the already-existing `run.timeline.*` stream) while the turn is still running, not only after it finishes; the composer clears on submit; a failed turn surfaces as `failed`, not stuck at `running` forever |
| Non-functional | No change to `handle_message`'s three other callers (CLI, legacy v1 `/chat`, `orchestration.py`); no new backend subsystem — reuses the existing `backend.jobs.queue` async job infrastructure and its established "handler registered in the same module that enqueues it" pattern (`backend/repository/indexing.py`'s precedent) |
| DoR (specific) | E43-S2 landed (a `run_id` is only useful early if the transcript renderer already does the right thing once given one) |
| DoD (specific) | Automated: `backend/tests/unit/orchestrator/test_begin_message.py` (immediate-return shape, synchronous KeyError/QuotaExceededError, real end-to-end completion via the actual background job, and a failed-job path releasing the lease); updated `test_chat_timeline_v2.py`/`test_cli_shell_api_only.py` for the new async contract; full backend + frontend suites green. Not performed: interactive browser click-through (no headless Chrome in this environment) |
| Dependencies | E43-S2, E43-S3 |

### E43-S7 — Live `run.timeline.*` events during Chat turns — **Complete**

Found via the user's live testing of E43-S6: even with async turn creation
landed, the Execution panel stayed on "Waiting" for the whole turn. Root
cause, distinct from S6's: `run.timeline.*` events were only ever emitted
by the "Run plan" task-dispatch pipeline (`_process_tasks`) — the Chat
turn's own agent graph (`_execute_message_run`'s `self._graph.invoke(...)`,
running navigator/analyzer/architect/coder/devops/validator/responder) has
never emitted them, since before this epic. Not a regression from S6; a
pre-existing gap this epic's original scope didn't cover.

Subtasks:
- `E43-S7-T1`: `_make_agent_node`'s node function now emits one
  `run.timeline.*` event per completed agent, reusing the exact event
  type/schema/role mapping `_process_tasks` already established
  (navigator/analyzer → analysis, coder → patch, validator → validation;
  planner/architect/devops/responder intentionally left off the
  four-stage timeline) — no new event type, no frontend change needed
  (`RunTimelinePanel` already renders whatever arrives on this stream).
- `E43-S7-T2`: `AgentGraphState` gains an optional (`NotRequired`)
  `tenant_id` field so the emitter knows which tenant to publish under,
  without touching the separate dynamic-routing graph in
  `backend/orchestrator/graphs.py` or any other existing construction of
  this state.

| Criterion | Detail |
| --- | --- |
| Functional | Sending a Chat message shows the Execution panel's four stages update live as navigator/analyzer/coder/validator each complete, with that agent's real output — not stuck on "Waiting" for the whole turn |
| Non-functional | No new event type or schema change; reuses `_process_tasks`'s existing mapping/output cap |
| DoR (specific) | E43-S6 landed (a `run_id` must exist early for this to be observable) |
| DoD (specific) | `test_handle_message_emits_live_timeline_events_per_agent` (order, mapping, real output content); updated `test_handle_message_completes_only_after_session_persistence` for the new event count; full backend suite green |
| Dependencies | E43-S6 |

## Contracts & decisions

- E43-S1 fixes execution correctness at the sandbox layer — it does not
  change the allowlist's security posture (still a fixed executable set),
  it only makes `cd`-prefixed commands parse correctly against it.
- E43-S2 is explicitly a rendering layer, not a new data source — it
  reuses E42-S1's event stream unchanged. If the transcript is ever found
  to need data the stream doesn't carry, that's a signal to extend the
  event payload (E9 contract), not to add a second, competing data path.
- E43-S4's file-read endpoint is deliberately read-only for this epic;
  in-app editing/writing files directly (bypassing the patch-review flow)
  is out of scope and should not be assumed as a natural next step without
  a separate, deliberate decision — the patch-apply/approval flow is the
  platform's intended write path.

## DoR / DoD

- **DoR:** E42 landed (S1's stream and S3's active-session concept must
  exist to extend); E43-S1 landed before E43-S2-T3 claims a passing
  command can be rendered (otherwise there is nothing but failures to
  show).
- **DoD:** all story DoDs met; a full Chat → Run plan rehearsal shows
  validation genuinely passing (not just genuinely reported), a readable
  terminal-style transcript with plain-language step labels, the generated
  project browsable and readable in-app, and every page reflecting the
  same active session by default; `docs/v2_platform/progress.md` updated;
  no push/PR without explicit authorization.

**Verification actually performed (2026-08-21):** every story has a
passing automated regression test (`backend/tests/unit/validation/
test_sandbox_runner.py`, `backend/tests/unit/execution/test_executor.py`,
`backend/tests/unit/api/test_repository_files_v2.py`, plus
`frontend/lib/__tests__/transcript.test.ts`); the full backend and
frontend unit suites pass; S4's new endpoints were confirmed live against
a throwaway backend instance (`curl` returned real directory/file content
from the configured project root) and the Files page was confirmed to
render server-side without error. **Not performed:** the full live
Chat → Run plan rehearsal this DoD calls for, and interactive
browser click-through of the transcript/file-browser UI — no headless
Chrome was available in the execution environment. Given E42-S5's own
claimed completion turned out (per this epic's own canonical source) to
not match what shipped, this gap should be closed with a real manual
pass in the product UI before treating this epic as unconditionally
signed off.
