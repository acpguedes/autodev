# E64 — Execution Panel: Real Technical Event Stream

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E63).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E42-S1 (unified run-event streaming), E43-S2/S3 (the shared
transcript formatter and step labels), E41-S3/S4 (patch-apply and
agent-declared commands), E33 (secret redaction inside `emit_event`)
**Enables:** a side panel that is a faithful record of what the platform did,
rather than a second rendering of what the model said — the thing E42-S5 and
E43-S2 each aimed at and neither finished.
**Canonical source:** this document, plus direct inspection of
`frontend/components/ExecutionConsolePanel.tsx`,
`frontend/components/chat/`, `backend/execution/executor.py` and
`backend/validation/sandbox.py` (2026-09-05).

## Context and problem

E42-S5 built a "live command execution panel". E43-S2 replaced its raw-JSON
rendering with a shared terminal-style formatter. Both landed. The panel still
duplicates the chat, and it is still not live — for reasons neither story
looked at, because both were scoped to *rendering*.

The chat panel mounts two components with two different data sources:

**`RunTimelinePanel`** (`frontend/components/chat/RunTimelinePanel.tsx` →
`ExecutionTimeline.tsx`, fed by `useRunTimeline.ts` over `run.timeline.*` SSE)
renders four fixed stages, each with a `<pre>` of `stage.output`. During a plan
execution that output is real: `build_timeline_output(outcome.results)`
concatenates stdout and stderr. During an ordinary **chat turn** it is
`agent_result.content` — the agent's raw LLM text, capped at 8000 characters,
emitted by `_emit_agent_timeline_event`
(`backend/orchestrator/service/graph.py:120-125,137-164`). So the panel's top
half restates the chat by construction.

**`ExecutionConsolePanel`** (`frontend/components/ExecutionConsolePanel.tsx`)
does read real action results — but from a **poll**, not a stream. Its `runs`
prop comes from `listRuns(sessionId)` (`frontend/lib/api.ts:210`), refreshed
only in `refreshSessionState()` after a turn or plan completes. And when a task
produced no actions, `buildConsoleEntries` falls back
(`ExecutionConsolePanel.tsx:75-93`) to rendering `result.metadata.description` —
the planner's LLM-written task description, presented in the same position as
command output. `derive_actions` (`backend/execution/executor.py:312`) produces
actions only for `validation`, `operations` and `implementation` categories, so
`planning`, `analysis` and `architecture` tasks always take that fallback.

Meanwhile the live path already exists and is used elsewhere:
`useExecutionActionLog` (`frontend/lib/execution_events.ts`) subscribes to
`execution.action.started|completed|failed` and renders through the same
`frontend/lib/transcript.ts` formatter — but only on the `/execution` page.

Three further gaps in what the events carry:

- **Output is not incremental.** `backend/validation/sandbox.py:341,371` — both
  `_run_docker` and `_run_local` call
  `subprocess.run(..., capture_output=True, timeout=..., check=False)`. One
  `started` event, then one `completed`/`failed` with the whole output,
  tail-capped at `_ACTION_OUTPUT_CHAR_CAP = 4000` (`executor.py:34`) — and the
  truncation is silent.
- **No event names the agent.** The payloads carry `actionId`, `taskId`,
  `stepLabel`, `command`, `path`, `stdout`, `stderr`, `exitCode`,
  `failureKind` — nothing identifies which agent originated the work, so
  concurrent execution cannot be attributed. The datum exists:
  `ExecutionTask.source_agent` (`backend/orchestrator/service/models.py:105`),
  already surfaced in `result.metadata.source_agent`
  (`task_outcomes.py:71`).
- **File reads emit nothing.** `ExecutionActionType`
  (`backend/execution/contracts.py:27-34`) has no read member, and there is no
  generic tool-call event: `backend/reasoning/`'s `TraceEvent`s
  (`contract.py:200`) are an internal list, and `grep emit_event
  backend/reasoning/` is empty.

## Evidence in code and documentation

- `frontend/app/page.tsx:181-199` — the panel's content and the auto-open rule.
- `frontend/components/ExecutionConsolePanel.tsx:56-108` —
  `buildConsoleEntries`, including the zero-action fallback at `:75-93`.
- `frontend/lib/transcript.ts` — `formatActionCommand`,
  `transcriptLineFromActionEvent`, `transcriptLineFromActionResult`; its header
  states it exists so the two surfaces cannot drift again.
- `frontend/lib/execution_events.ts` — `useExecutionActionLog` and
  `EXECUTION_ACTION_EVENT_TYPES`.
- `frontend/lib/api_v2.ts` — `runEventsStreamUrl()`, `parseSseBuffer()`, and
  `SseFrame.id`, which carries the bus cursor.
- `backend/api/routers/runs_stream_v2.py` — `_stream_events`; with no `cursor`
  it calls `bus.replay_from(run_id, None)`, replaying the run's full history
  before tailing live. This is the fact that makes E64-S1's merge simple.
- `backend/events/bus.py` — the in-memory bus's retained-length bound, which is
  why a fallback to the polled history is still needed.
- `backend/events/catalog.py:265-322` — the three `ExecutionAction*Data`
  payloads, and how `stepLabel`/`failureKind` were added as optional fields
  without a schema-version bump.
- `backend/execution/executor.py:34,133-249,312` — the output cap, the five
  emit sites, and `derive_actions`.
- `backend/validation/sandbox.py:341,371` — the two blocking `subprocess.run`
  calls.
- `frontend/e2e/execution-approval.spec.ts:79-89` — an existing Playwright mock
  of an SSE body of `execution.action.*` frames; the model for E64's e2e.

## Objective

Make the execution panel a faithful, live record of real tool and process
events — command, output, state, exit code, and file operations — attributable
per agent, with nothing generated by a model rendered as if it were output.

## Key result

Running a command during a turn shows its real command line the moment it
starts, its stdout and stderr as they arrive, its state and exit code when it
ends — and the panel contains no sentence written by an agent.

## Scope

- Removing every model-generated string from the panel.
- Making the panel consume the existing SSE stream, with the polled history as
  the reload/fallback path.
- Agent attribution and explicit exit-code and truncation rendering.
- Incremental stdout/stderr, on both the Docker and local sandbox paths.
- A real file-read action so read operations can be shown honestly.

## Out of scope

- Deleting `RunTimelinePanel`/`ExecutionTimeline`/`useRunTimeline`/`lib/timeline.ts`
  or the `run.timeline.*` event family. They are covered by
  `frontend/lib/__tests__/timeline.test.ts`, and removing the event family is a
  larger call than this epic; the components stop being mounted in the panel and
  nothing else.
- `frontend/components/RunEventStream.tsx`, which duplicates the SSE-consumer
  logic `lib/execution_events.ts` owns. Recorded as a follow-up, not fixed here.
- Token-level LLM streaming: `agent.token.delta` is catalogued and emitted by
  nothing. Out of scope, and left as-is.
- Any change to what the chat itself renders.

## Stories

### E64-S1 — Live, technical-only panel

Subtasks:
- `E64-S1-T1`: stop mounting `RunTimelinePanel` in the chat panel
  (`frontend/app/page.tsx` is its only importer, so this is pure subtraction).
  Removing only its `<pre>` is not sufficient: the four stages derive from
  *agent roles* (`timeline_event_type_for_agent_role`), not from tool events, so
  what would remain satisfies none of the requirements while adding a second
  ordering axis to reconcile against the action stream.
- `E64-S1-T2`: delete the zero-action fallback in `buildConsoleEntries`
  (`ExecutionConsolePanel.tsx:75-93`). A task that dispatched no action renders
  **nothing** — the panel is a record of operations, and a task with no
  operation has no entry.
- `E64-S1-T3`: give `ExecutionConsolePanel` an `activeRunId` prop and subscribe
  it to `useExecutionActionLog`. Because a cursor-less stream replays the run's
  whole history first, SSE alone is complete for the active run: entries for the
  active run come from the stream, entries for other runs come from the polled
  `runs` prop filtered to `run_id !== activeRunId`. If the stream errors, drop
  the filter so the polled history covers the active run too — the in-memory bus
  bounds its retained length and loses everything on restart, so this is a real
  path, not a theoretical one.
- `E64-S1-T4`: merge on a `Map` keyed by `actionId`, collapsing a `started` and
  its terminal `completed`/`failed` into one entry, and sort by the SSE frame
  `id` (the bus cursor, monotonic within the run's partition). That ordering is
  what preserves received order when several operations run at once.

| Criterion | Detail |
| --- | --- |
| Functional | The panel updates while a turn runs; every entry is a real operation; no model-written text appears |
| Non-functional | No new backend surface; one entry per `actionId` regardless of source; received order preserved |
| DoR (specific) | none beyond E42-S1/E43-S2 |
| DoD (specific) | Component tests: a zero-action result renders no entry; an `actionId` present in both SSE and `runs` renders once; `started`+`completed` collapse into one entry |
| Dependencies | E42-S1, E43-S2 |

### E64-S2 — Agent attribution, exit code and truncation

Subtasks:
- `E64-S2-T1`: add an optional `source_agent` to `ExecutionAction`
  (`backend/execution/contracts.py`), populate it at the five `ExecutionAction(...)`
  construction sites in `derive_actions` from `ExecutionTask.source_agent`, add an
  optional `sourceAgent` to the three `ExecutionAction*Data` payloads, and include
  it at the five `emit_event` sites — exactly the additive shape by which
  `stepLabel` (E43-S3) and `failureKind` (E46-S1) were added, with no
  `schemaVersion` bump.
- `E64-S2-T2`: render the operation's state explicitly — running, completed,
  cancelled, failed — and the exit code as its own field rather than buried in
  the output text.
- `E64-S2-T3`: render a truncation notice when output hit
  `_ACTION_OUTPUT_CHAR_CAP`. Today a 4000-character tail is presented as if it
  were the whole output, which is a quieter version of the same honesty problem
  this epic exists to fix.

| Criterion | Detail |
| --- | --- |
| Functional | Each entry names its originating agent, its state and its exit code; truncated output says so |
| Non-functional | Additive event fields; a pre-E64 event without `sourceAgent` still renders |
| DoR (specific) | E64-S1 merged |
| DoD (specific) | Backend tests asserting `sourceAgent` on started/completed/failed; a frontend test that an event without it still renders |
| Dependencies | E64-S1 |

### E64-S3 — Incremental stdout and stderr

Subtasks:
- `E64-S3-T1`: replace the blocking `subprocess.run(capture_output=True)` with
  incremental reading on **both** sandbox paths (`_run_docker` and `_run_local`,
  `backend/validation/sandbox.py:341,371`), keeping the module free of the event
  bus by taking an optional `on_chunk` callback — **the executor emits**, so
  redaction and the emit convention stay in one place.
- `E64-S3-T2`: append `execution.action.output` `{actionId, stream, chunk, seq}`
  to `EVENT_CATALOG` (append-only), and consume it in the panel by appending to
  the entry already keyed by `actionId`.
- `E64-S3-T3`: close the redaction boundary. Secret redaction runs inside
  `emit_event()` (E33), and a secret split across two chunks defeats a
  per-event redactor. Emit on line boundaries with a carry-over window, and test
  exactly that case with a deliberately split secret fixture.
- `E64-S3-T4`: preserve the timeout semantics `subprocess.run(timeout=)` gave
  for free, and fix what it was hiding: killing the `docker run` client does not
  stop the container, so the Docker path needs an explicit `docker kill` on
  timeout. Also handle decode and newline boundaries and avoid the classic
  two-pipe deadlock on both paths.

| Criterion | Detail |
| --- | --- |
| Functional | stdout and stderr appear in the panel while the process is still running |
| Non-functional | A secret split across a chunk boundary is still redacted; a timed-out container is actually stopped; the final event's content is unchanged |
| DoR (specific) | E64-S1 merged; the split-secret redaction approach agreed |
| DoD (specific) | A split-secret fixture proving redaction across chunks; a timeout test asserting the container is killed; an equivalence test that the completed event's output matches the pre-change behavior |
| Dependencies | E64-S1, E33 |

### E64-S4 — File read operations

*The one story in this epic that adds capability rather than repairing a defect.
The reason is recorded under "Declared scope limits" below and must not be
quietly dropped.*

Subtasks:
- `E64-S4-T1`: add a `read_file` member to `ExecutionActionType` and a runner
  for it, so reading a file on behalf of an agent is a real, policy-checked,
  auditable action like writing one — rather than an invisible side effect.
- `E64-S4-T2`: use it where a task genuinely needs a file's contents, typically
  before editing it, and emit the same `execution.action.*` events with `path`
  set.
- `E64-S4-T3`: render `Reading: <path>` and `Editing: <path>` as concise
  summaries, extending `formatActionCommand`
  (`frontend/lib/transcript.ts:67-75`), which already renders `$ write <path>`
  for the write types.

| Criterion | Detail |
| --- | --- |
| Functional | A read performed for an agent appears in the panel, with its path, without a shell being involved |
| Non-functional | Reads go through the same containment guard and policy path as writes; no new bypass |
| DoR (specific) | E64-S1 merged |
| DoD (specific) | A test that a read outside the project root is refused by the same guard that refuses a write; a rendering test for the read line |
| Dependencies | E64-S1 |

## Declared scope limits

**`Reading: <file>` requires creating the capability, not just rendering it.**
Verified before scoping E64-S4, because the honest answer changes the story:
`ExecutionActionType` has no read member; `FilesContextProvider`
(`backend/context/providers/files.py:48`) holds the only `read_text` in
`backend/context/` and nothing in `backend/orchestrator/` constructs it;
`backend/repository/retrieval/retriever.py::retrieve` has exactly one caller in
the whole backend (`backend/api/routers/context.py:106`), a user-facing API
route rather than the turn path; and `backend/reasoning/engine.py::call_tool`
records only internal `TraceEvent`s. **During a chat turn, no agent reads a
file.** The requirement is therefore satisfiable only by making reads real —
the alternative would be synthesising the line from LLM text, which is precisely
the defect this epic exists to remove.

## Contracts and decisions

### Architectural decisions required

- No new ADR for E64-S1/S2: the event payload changes are additive optional
  fields, the pattern `stepLabel` and `failureKind` already established.
- `execution.action.output` is a new event type — additive to an append-only
  catalog, which §19.1 treats as a MINOR change; a lightweight ADR is warranted
  for the chunk-redaction rule specifically, since it is a security property
  that every future streaming producer must honor.
- `read_file` extends the execution action contract governed by RFC-009 /
  ADR-021; record the extension there rather than in a competing document.

### Security and multitenancy

- Redaction remains inside `emit_event()` and must hold across chunk boundaries
  (E64-S3-T3). This is the single security-relevant change in the epic.
- Read actions are subject to the same policy engine and the same root
  containment guard as writes; adding a read type must not create a path that
  bypasses either.
- The panel renders only what the stream carries; it must not fetch file
  contents to enrich an entry.

### Migration strategy

- None. No schema change, no migration. Old events lacking `sourceAgent` render
  with the existing fallbacks.

### Compatibility and rollback

- Rollback of E64-S1 restores the previous panel composition; the SSE hook and
  formatter are unchanged and shared with `/execution`.
- Rollback of E64-S3 restores blocking capture; the completed event's content is
  identical either way, which is what E64-S3-T4's equivalence test protects.

## Testing and observability

Tests required:
- Zero-action result renders no entry.
- Same `actionId` from SSE and poll renders once.
- `started` + `completed` collapse, exit code shown.
- Event without `sourceAgent` still renders.
- Split-secret redaction across chunks.
- Docker timeout kills the container.
- Completed-event output equivalence before and after incremental capture.
- Read refused outside the project root; read line rendered.
- End to end: the panel shows a real command with its stdout and does **not**
  show the assistant's message text — extending
  `frontend/e2e/execution-approval.spec.ts`'s existing SSE mock.

Observability:
- Every panel entry is reconstructible from durable events alone; the polled
  path is a convenience, never the source of truth.
- `run.timeline.*` becomes an unconsumed event family in the chat panel. Flag it
  in the epic PR; do not delete it here.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Secret split across a chunk boundary escapes redaction | Credential disclosure — a new exfiltration path created by this epic | Line-boundary emission with carry-over, proven by a deliberately split fixture (E64-S3-T3); the story does not land without it |
| `Popen` loses the timeout guarantees `subprocess.run` provided | A hung command holds a run forever; a timed-out container keeps running | E64-S3-T4 covers timeout, container kill, decode boundaries and deadlock explicitly |
| Removing the fallback leaves the panel empty for planning-heavy turns | Users read emptiness as breakage | Empty state copy says what the panel shows and why nothing is there; the chat still carries the narrative |
| Bus history loss makes a reloaded old run render empty | Apparent data loss | Polled history covers the active run when the stream errors (E64-S1-T3) |
| Adding a read action widens the executor's surface | More code paths under policy | Reads reuse the existing policy and containment guard; the guard test is the DoD |

## DoR / DoD

- **DoR:** E42-S1, E43-S2/S3 and E33 merged; the chunk-redaction ADR written.
- **DoD:** all four story DoDs met; no model-generated text in the panel, proven
  by the e2e assertion; output visible while a process runs; entries attributed,
  stated and exit-coded; split-secret redaction proven; read operations real and
  guarded; `docs/v2_platform/progress.md` updated.

## Affected documents and code

Documents: `docs/execution/engine.md`,
`docs/v2_platform/decisions/RFC-009-execution-action-contract.md` (extension),
a new lightweight ADR, `docs/v2_platform/progress.md`, `CHANGELOG.md`.

Code: `frontend/components/ExecutionConsolePanel.tsx`,
`frontend/lib/execution_events.ts`, `frontend/lib/transcript.ts`,
`frontend/app/page.tsx`, `frontend/locales/en.json`,
`frontend/locales/pt-BR.json`, `backend/execution/executor.py`,
`backend/execution/contracts.py`, `backend/execution/runner.py`,
`backend/events/catalog.py`, `backend/validation/sandbox.py`.
