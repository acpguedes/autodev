# E43 — Execution Transparency: Terminal Transcript, File Browser & Session Stickiness

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35, E41, and E42: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E42 (specifically E42-S1's event stream and E42-S3's
active-session concept — both real and reused here, not rebuilt), E41-S3
(patch-apply actions), E41-S4 (agent-directed commands)
**Enables:** genuine transparency into what the platform did to a project —
today a user can see that something ran, but not read it the way they would
read their own terminal
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

## Objective

E42-S1 proved the event plumbing is real (SSE stream genuinely delivers
`run.timeline.*`/`execution.*` events for Chat-triggered runs). E42-S5
consumed that plumbing but rendered it as a raw JSON dump — technically
"live," not actually readable. This epic builds the missing rendering layer
on top of E42-S1's already-working stream, adds a way to actually see the
files the platform wrote without leaving the browser, and makes "which
session am I looking at" consistent across the whole app instead of
per-page.

## Key result

Watching a run in the browser reads like watching your own terminal: each
action appears as a command line with its real output (a patch-apply shows
what file it wrote and a summary of the change; a validation command shows
its real stdout/stderr), each step carries a plain-language label like
"Creating main.py," the project's file tree is browsable and every file
readable in-app, and navigating to any page (Chat, Plans, Execution,
Patches) shows the session you were just looking at by default.

## Stories

### E43-S1 — Terminal-style transcript rendering (supersedes E42-S5's raw JSON view) — **Not started**

Subtasks:
- `E43-S1-T1`: a transcript renderer that consumes the same
  `run.timeline.*`/`execution.*` SSE events E42-S1 already streams and
  turns each into one terminal-style line — a synthetic command prompt plus
  real output — rather than displaying the event's JSON payload directly.
- `E43-S1-T2`: patch-apply actions (E41-S3) render as a write command (e.g.
  a `$ write main.py` style line) followed by a concise summary of what
  changed (not necessarily the full diff inline — link/expand to it), so
  "which command was used to write a file" is answered directly instead of
  requiring the user to parse a `PatchResult.message` string out of JSON.
- `E43-S1-T3`: real validation/devops commands (E41-S4) render as an actual
  `$ pytest` (etc.) line with real stdout/stderr streamed beneath it as it
  arrives, not only a final status.
- `E43-S1-T4`: replace the current raw-JSON side panel content with this
  renderer; the raw-event view may remain available behind an explicit
  "view raw event" toggle for debugging, but is not the default.

| Criterion | Detail |
| --- | --- |
| Functional | Every patch-apply and command action in a run appears as a readable terminal-style line with its real output, in chronological order, with no JSON visible by default |
| Non-functional | No new backend surface — this is a rendering layer over E42-S1's existing stream |
| DoR (specific) | E42-S1 landed (confirmed working) |
| DoD (specific) | Manual verification: trigger a run with both a patch-apply and a validation command, observe both rendered as transcript lines |
| Dependencies | E42-S1, E41-S3, E41-S4 |

### E43-S2 — Step-level plain-language annotations — **Not started**

Subtasks:
- `E43-S2-T1`: surface each task's human-readable title/description (already
  present in execution metadata, e.g. "Implement Main Application File") as
  a small label/header above its transcript entry — "Creating `main.py`"
  rather than a bare `task_id` like `coding-file-1`.
- `E43-S2-T2`: apply the same treatment to non-file steps (planning,
  analysis, validation) so the whole transcript reads as a narrated
  sequence, not just the file-writing steps.

| Criterion | Detail |
| --- | --- |
| Functional | Every transcript entry from E43-S1 carries a plain-language label derived from its task metadata, not a raw task/step ID |
| Non-functional | Falls back gracefully (shows the raw id) when a task genuinely has no description |
| DoR (specific) | E43-S1 landed |
| DoD (specific) | Manual verification across planning/analysis/patch/validation entries |
| Dependencies | E43-S1 |

### E43-S3 — Project file tree browser + in-app file viewer — **Not started**

A new capability — no existing endpoint lists a project's file tree or
serves raw file content scoped to `project_root`; the closest existing
thing (`/v2/repository/context`) is ranked RAG context, not a browsable
tree.

Subtasks:
- `E43-S3-T1`: new read-only backend endpoint(s) to list the active
  session's `project_root` as a file tree and to fetch one file's raw
  content by relative path — guarded by the same root-containment check
  already proven in `backend.patches.engine.apply_patch` (reject anything
  resolving outside `project_root`), applied here to reads instead of
  writes.
- `E43-S3-T2`: a file-tree panel (sidebar or dedicated tab) driven by that
  endpoint, showing the generated project's actual structure.
- `E43-S3-T3`: clicking a file opens its content in-app (read-only viewer,
  syntax-highlighted where reasonable) — no download/external-editor
  round-trip required to see what the platform wrote.

| Criterion | Detail |
| --- | --- |
| Functional | A user can browse the active session's project tree and read any file's current content without leaving the browser |
| Non-functional | Read-only; the traversal guard rejects any path escaping `project_root`, mirroring the existing patch-apply guard |
| DoR (specific) | none beyond an active session with a resolved `project_root` |
| DoD (specific) | Test asserting the path-traversal guard rejects an escaping path, mirroring `apply_patch`'s existing test |
| Dependencies | E41 (project_root resolution) |

### E43-S4 — App-wide session stickiness — **Not started**

Broadens E42-S3 (which only fixed Plans/Execution) to every page.

Subtasks:
- `E43-S4-T1`: a single shared "active session" concept read by every page
  — Chat, Plans, Execution, Patches, and E43-S3's new file browser — instead
  of each page independently deciding its own default (or none).
- `E43-S4-T2`: selecting/creating a session anywhere in the app updates
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

## Contracts & decisions

- E43-S1 is explicitly a rendering layer, not a new data source — it
  reuses E42-S1's event stream unchanged. If the transcript is ever found
  to need data the stream doesn't carry, that's a signal to extend the
  event payload (E9 contract), not to add a second, competing data path.
- E43-S3's file-read endpoint is deliberately read-only for this epic;
  in-app editing/writing files directly (bypassing the patch-review flow)
  is out of scope and should not be assumed as a natural next step without
  a separate, deliberate decision — the patch-apply/approval flow is the
  platform's intended write path.

## DoR / DoD

- **DoR:** E42 landed (S1's stream and S3's active-session concept must
  exist to extend); E43-S3-T1's endpoint design reviewed against the
  existing `apply_patch` guard pattern before implementation.
- **DoD:** all story DoDs met; a full Chat → Run plan rehearsal shows a
  readable terminal-style transcript with plain-language step labels, the
  generated project is browsable and readable in-app, and every page
  reflects the same active session by default; `docs/v2_platform/progress.md`
  updated; no push/PR without explicit authorization.
