# E43 — Execution Transparency: Terminal Transcript, File Browser & Session Stickiness

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35, E41, and E42: added after initial Beta
completion, before the wave is signed off).
**Status:** Not started · **Stories:** 0/5
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

### E43-S1 — Fix sandboxed execution for `cd`-prefixed commands — **Not started**

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

### E43-S2 — Terminal-style transcript rendering (supersedes E42-S5's raw JSON view) — **Not started**

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

### E43-S3 — Step-level plain-language annotations — **Not started**

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

### E43-S4 — Project file tree browser + in-app file viewer — **Not started**

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

### E43-S5 — App-wide session stickiness — **Not started**

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
