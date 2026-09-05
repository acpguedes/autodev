# E65 — Interactive Terminal

**Wave:** v2.0-beta — "full platform in controlled production" (Beta-hardening
extension, same pattern as E32-E35 and E41-E64).
**Status:** Not started · **Stories:** 0/4
**Depends on:** E62 (a project to bind a session to), E11-S2 (Control Plane
RBAC and the access audit record, ADR-018), E15-S2 (the shell's execution panel
slot), E32/E14 (the fail-closed execution posture this epic mirrors)
**Enables:** the user working in their own project from the same surface the
agent works in — the missing half of "watching a run reads like watching your
own terminal" (E43's key result), which today is read-only.
**Canonical source:** this document, plus direct inspection of
`backend/api/`, `backend/auth/`, `frontend/components/shell/` and
`frontend/next.config.mjs` (2026-09-05).

## Context and problem

There is no terminal. This is not a partial implementation to finish; it is a
capability that does not exist, verified rather than assumed:

- `xterm` — **zero** occurrences in the repository, including
  `frontend/package.json`.
- `pty` / `openpty` / `forkpty` / `ptyprocess` — one occurrence:
  `backend/plugins/permissions.py:15`,
  `EXEC_MODULES = frozenset({"subprocess", "pty"})`, a **denylist** of modules
  plugins may not import.
- `websocket` — no backend route and no frontend client. The only hits are
  `frontend/next.config.mjs`'s dev-only `ws:` CSP entry and documentation
  describing something unbuilt:
  `docs/architecture/v2_platform_reference.md:3832`
  (`| WS | /v2/ws | Bidirectional WebSocket channel |`), §14.4, and
  `docs/v2_platform/phases/e9_apis_events_mcp.md:44`.
- The only "shell" is `backend/cli_shell.py` — `autodev --shell`, a Python REPL
  that talks to `/v2` over `httpx`. It has no PTY and does not stream;
  `docs/execution/shell.md` says so under "Scope note: no live SSE streaming in
  the shell".

E43 delivered a terminal-*styled* transcript: monospace `<pre>`/`<code>` over
real events. What it cannot do is let a user type. Every requirement in this
epic — a persistent shell session preserving working directory and environment,
interactive input, interrupting a running command — needs a pseudo-terminal and
a bidirectional transport, and the platform has neither.

Two constraints shape the design, both discovered rather than assumed:

**The app-level authorization middleware breaks on a WebSocket handshake.**
`AuthService.authenticate_request` (`backend/auth/service.py:231`) reads only
`request.headers` and `request.cookies`, both of which exist on Starlette's
`WebSocket`, so it works duck-typed. But `enforce_control_plane_access`, wired
at `backend/api/main.py:297`, touches `request.method`, which a `WebSocket` does
not have — an `AttributeError` on every handshake. The route therefore needs an
explicit, audited authorization path rather than the ambient one.

**The panel's content is owned by the page, and dies with it.**
`useExecutionPanel`'s cleanup (`frontend/components/shell/ShellProvider.tsx:168-171`)
nulls `panelContent` when the page unmounts. A terminal mounted in page-owned
content would be destroyed on every route change — which is exactly what a
persistent session must not do.

## Evidence in code and documentation

- `backend/plugins/permissions.py:15` — `pty` in the plugin import denylist,
  the repository's only mention of it.
- `docs/architecture/v2_platform_reference.md:3832` and §14.4 — the reserved,
  unimplemented `WS /v2/ws`.
- `backend/cli_shell.py`, `docs/execution/shell.md` — the existing non-PTY shell.
- `backend/auth/service.py:231` — `authenticate_request`.
- `backend/api/main.py:297` — where `enforce_control_plane_access` is wired.
- `backend/api/authorization.py` — `requires_scope`, `public_endpoint`, the
  `AccessAuditRecord` write; ADR-018 requires an allow to be auditable.
- `backend/api/routers/__init__.py` — router auto-discovery, so a new module
  exposing `router` needs no wiring.
- `backend/api/routers/runs_stream_v2.py::_stream_events` — the existing
  worker-thread → event-loop marshalling pattern this epic reuses.
- `backend/validation/sandbox.py` — `SandboxPolicy`,
  `sandbox_policy_from_settings`, and the `AUTODEV_ENABLE_SANDBOX` /
  `AUTODEV_SANDBOX_ALLOW_LOCAL` fail-closed posture this epic mirrors.
- `frontend/components/shell/ExecutionPanelSlot.tsx`,
  `ShellProvider.tsx:165-171`, `shellStore.ts` — the panel slot, the cleanup,
  and the persisted shell state (`autodev.shell.v1`).
- `frontend/components/ui/tabs.tsx` over `@radix-ui/react-tabs` — already
  installed.
- `frontend/next.config.mjs` — `connect-src` built from `NEXT_PUBLIC_API_URL`
  with `http://localhost:8000` / `http://127.0.0.1:8000` fallbacks; `ws:` allowed
  only in dev.

## Objective

Give the user a real interactive shell in the active project, from the product
surface, without weakening the platform's fail-closed execution posture.

## Key result

Opening the Terminal tab lands in the active project's root; `cd` in one command
is still in effect in the next; Ctrl-C interrupts a running command; the header
says which project and directory the session belongs to; and switching projects
never continues in the previous project's shell.

## Scope

- A PTY session manager with a long-lived shell per terminal session.
- A WebSocket route with an explicit, audited authorization path.
- A frontend terminal tab living in the shell's panel slot.
- Binding every session to a project, structurally.
- A fail-closed feature flag and its documentation.

## Out of scope

- The generic multiplexed `WS /v2/ws` channel reserved in reference §14.4. This
  epic builds the narrow `/v2/terminal/{id}` route and records the divergence in
  that section rather than pretending the general channel now exists.
- Running the terminal inside the E32 hardened container. The trade-off is
  recorded under "Contracts and decisions"; `docker exec` into a long-lived
  per-project container is the eventual answer and needs container lifecycle,
  image management and a writable mount — a separate epic.
- Multi-worker deployment of terminal sessions (see Risks).
- Replacing `autodev --shell`, which is a different thing and keeps working.
- Recording or replaying terminal sessions.

## Stories

### E65-S1 — PTY session manager

Subtasks:
- `E65-S1-T1`: a new `backend/terminal/session.py` — a `TerminalSession` over
  `pty.fork()` (rather than `openpty` + `Popen`, which would need `setsid` by
  hand for correct controlling-terminal semantics), running the user's shell
  interactively with `cwd` set to the project root and `TERM=xterm-256color`,
  and an environment that is an allowlisted copy of the process environment with
  everything the secret store injects removed.
- `E65-S1-T2`: one daemon reader thread per session —
  `select.select([master_fd], [], [], 0.2)` then `os.read` — marshalling into
  the event loop with `call_soon_threadsafe`, the same pattern
  `runs_stream_v2._stream_events` already uses. Bounded scrollback (64 KiB)
  retained so a reattach shows recent context. Window resize via
  `fcntl.ioctl(TIOCSWINSZ)` followed by `SIGWINCH`. Teardown as
  `SIGHUP` → grace → `SIGKILL` → `waitpid`, so no zombie is left behind.
  **Ctrl-C needs no API**: the client sends `\x03` and the line discipline
  raises `SIGINT` on the foreground process group.
- `E65-S1-T3`: a `backend/terminal/manager.py` holding sessions keyed by
  `(tenant_id, project_root, terminal_id)`. Because the project root is part of
  the key, a session belonging to another project is structurally unreachable —
  silent reuse across projects is not prevented by a check that could be
  forgotten, it is impossible. Idle TTL and a per-tenant session cap, both swept
  lazily on attach and on disconnect, so no new scheduler is introduced.
- `E65-S1-T4`: the fail-closed gate — a new `AUTODEV_ENABLE_TERMINAL` setting
  defaulting to off, placed beside `autodev_enable_sandbox` and
  `autodev_sandbox_allow_local` in `backend/config/settings.py`, plus a refusal
  to start under the `prod` profile unless explicitly overridden.

| Criterion | Detail |
| --- | --- |
| Functional | A session preserves working directory and environment across commands; Ctrl-C interrupts; resize is honored; the session starts in the project root |
| Non-functional | Disabled by default; no zombie processes; no file descriptor leak; sessions reaped on idle |
| DoR (specific) | E62-S3 merged (a per-session project root exists) |
| DoD (specific) | Tests: `echo` round trip; `\x03` during a long-running command and the shell recovers; `close()` reaps the child; **the same terminal id under a different project root yields a different session** |
| Dependencies | E62-S3 |

### E65-S2 — WebSocket transport with an audited authorization path

Subtasks:
- `E65-S2-T1`: `WS /v2/terminal/{terminal_id}` in a new
  `backend/api/routers/terminal_v2.py`, auto-registered by the routers package.
  Build the narrow route, and record the divergence from reference §14.4's
  general channel in that section.
- `E65-S2-T2`: an `authorize_websocket(websocket, scope)` helper in
  `backend/api/authorization.py` that authenticates, checks a new `terminal:use`
  scope, and **writes the `AccessAuditRecord`** with `method="WEBSOCKET"` — the
  handler is marked `@public_endpoint` so the app-level middleware does not
  crash on the missing `request.method`, which means the audit ADR-018 requires
  would otherwise be skipped. Failure closes the socket (`4401` / `4403`)
  before `accept()`.
- `E65-S2-T3`: authenticate with the same session cookie the SSE stream already
  relies on. **Reject a `?token=` query parameter explicitly** — query strings
  reach access logs and `Referer` headers, and adding that surface for a
  terminal is not a trade worth making.
- `E65-S2-T4`: a small JSON frame protocol — client sends input and resize,
  server sends an opening `info` frame naming the project root, output, and a
  terminal `exit` frame. The server resolves the project root itself and never
  accepts it from the client.

| Criterion | Detail |
| --- | --- |
| Functional | An authorized client attaches and exchanges input and output; an unauthorized or unscoped client is closed before `accept()` |
| Non-functional | Every allow is audited; no credential in a URL; the project root is server-resolved |
| DoR (specific) | E65-S1 merged; the `terminal:use` scope added to the role map |
| DoD (specific) | Tests: closes `4403` with the flag off; closes `4401` unauthenticated; emits `info` with the project root when enabled; the contract authorization suite extended, since its `protected_routes_without_requirement` check iterates HTTP routes only and would not catch a WebSocket |
| Dependencies | E65-S1, E11-S2 |

### E65-S3 — Frontend terminal tab

Subtasks:
- `E65-S3-T1`: add `@xterm/xterm` and `@xterm/addon-fit` at exact pinned
  versions, matching how the repository pins `next`, `react` and `swr`.
- `E65-S3-T2`: a `frontend/lib/terminal_socket.ts` deriving the socket URL from
  the same base the REST client uses (`http:`→`ws:`, `https:`→`wss:`) and owning
  the frame encoding — **without importing xterm**, so it stays jsdom-testable
  the way `lib/execution_events.ts` is. `TerminalPanel.tsx` loads via
  `next/dynamic(..., { ssr: false })` because xterm touches `window` at import,
  and takes its theme from the `ds-*` CSS variables so it does not fight dark
  mode.
- `E65-S3-T3`: put the tab strip **in `ExecutionPanelSlot`**, not in the page.
  Two tabs on the already-installed `components/ui/tabs.tsx`: *Activity*
  renders the page-owned `panelContent` unchanged, *Terminal* renders the
  terminal, which therefore survives navigation instead of being torn down by
  `useExecutionPanel`'s cleanup. Persist the selected tab through `ShellState`
  and `sanitizeShellState` in `shellStore.ts`.
- `E65-S3-T4`: the supporting changes a new transport needs: add the WebSocket
  origin to `connect-src` in `frontend/next.config.mjs`, derived from the API
  origin with `ws://localhost:8000` / `ws://127.0.0.1:8000` in the fallback
  branch; and add a `terminal.*` namespace to **both** locale files, which are
  parity-tested and lint-enforced against literals.

| Criterion | Detail |
| --- | --- |
| Functional | A user runs commands from the Terminal tab; the session survives navigating between pages |
| Non-functional | xterm is not in the main bundle; the terminal renders correctly in both themes; both locales in parity |
| DoR (specific) | E65-S2 merged |
| DoD (specific) | Playwright spec using `page.routeWebSocket()`: output renders and typing emits an input frame; a shell-store test for tab persistence and sanitization of a bad stored value |
| Dependencies | E65-S2 |

### E65-S4 — Project binding, ADR and documentation

Subtasks:
- `E65-S4-T1`: the terminal id is generated client-side and stored per project
  root in the shell store; the client also compares the server's `info.projectRoot`
  against the active project and, on a mismatch, discards the id and offers to
  start a new session rather than continuing in an ambiguous one. The server-side
  key already makes cross-project reuse impossible; this makes the *user-visible*
  behavior explicit rather than silent.
- `E65-S4-T2`: an ADR recording the two decisions this epic rests on: the PTY
  runs on the host behind a fail-closed flag rather than in the E32 container,
  and the frontend is corrected incrementally rather than rebuilt.
- `E65-S4-T3`: `docs/execution/terminal.md`, stating plainly that an enabled
  terminal grants the caller the privileges of the server process — in the same
  paragraph as `AUTODEV_SANDBOX_ALLOW_LOCAL`, so the two flags are read
  together.

| Criterion | Detail |
| --- | --- |
| Functional | Switching projects never continues in the previous project's shell, and the user is told why |
| Non-functional | The security posture is documented where an operator will actually read it |
| DoR (specific) | E65-S3 merged |
| DoD (specific) | A test that a stale terminal id under a new project root produces a new session, not the old one |
| Dependencies | E65-S3 |

## Contracts and decisions

### Architectural decisions required

- **Host PTY behind a fail-closed flag** (new ADR, E65-S4-T2). The E32 hardened
  container — `--network=none`, `--read-only`, `--user=65534:65534`,
  `--cap-drop=ALL`, read-only bind mount — is a *batch* execution surface. A
  terminal in which the user cannot install a dependency, cannot write a file,
  and whose `cd` is discarded is not the capability being asked for. The
  developer terminal whose purpose is running the project's own tooling in the
  project's own tree runs on the host, default off, scoped, audited and
  documented. `docker exec` into a long-lived per-project container is the
  eventual answer and is named as such, not implemented here.
- **Narrow route rather than the reserved general channel.** Reference §14.4's
  `WS /v2/ws` stays unimplemented; §14.4 is updated to say so and to point at
  `/v2/terminal/{id}`.
- **Frontend corrected incrementally** (same ADR). The shell's panel slot, the
  SSE plumbing and the shared transcript formatter already exist; the new
  dependency is xterm, which is framework-independent. A stack change would cost
  the parity-tested i18n, the Storybook stories, the Playwright suite and the
  `ds-*` design system, and would remove none of the actual defects.

### Security and multitenancy

- `terminal:use` is a distinct scope, mirroring the `quota:read`/`quota:admin`
  and `secret:use`/`secret:manage` splits.
- Every allow is audited (E65-S2-T2), because `@public_endpoint` would otherwise
  skip the record ADR-018 requires.
- The session environment is an allowlisted copy with injected secrets removed,
  so a terminal is not a way to read the secret store's injections.
- **Terminal output is not redacted.** The E33 redactor lives in `emit_event()`
  and this path does not go through it. Consequence: terminal output is never
  logged server-side, and that is a rule, not a preference.
- Two independent gates keep the default posture: the flag is off, and the
  `prod` profile refuses without an explicit override.

### Migration strategy

- None. No schema change; sessions are process-local runtime state by design.

### Compatibility and rollback

- With the flag off — the default — the product behaves exactly as before; the
  tab is absent rather than broken.
- Rollback is disabling the flag; no data is written that a rollback would
  strand.

## Testing and observability

Tests required:
- `echo` round trip; `\x03` interrupt with recovery; resize; clean reap.
- Same key returns the same session; different project root returns a different
  one; idle reap; per-tenant cap.
- WebSocket closes `4403` with the flag off, `4401` unauthenticated; `info`
  frame carries the project root when enabled.
- The contract authorization suite covers the WebSocket route.
- URL scheme mapping and frame encoding.
- Tab persistence and sanitization.
- Playwright: output renders, typing emits an input frame.

Observability:
- Session lifecycle emits catalog events following the past-tense
  `domain.entity.action` convention, so an operator can see that a terminal was
  opened, by whom, in which project — **without** the session's contents.
- The access audit record is the authorization trail; the event catalog is the
  lifecycle trail. Neither carries terminal output.

## Risks and mitigation

| Risk | Impact | Mitigation |
| --- | --- | --- |
| A PTY in the API process is code execution as the server user | The largest privilege expansion in the Beta wave | Off by default; `prod` refuses without an explicit override; dedicated scope; every allow audited; stated plainly in the docs beside `AUTODEV_SANDBOX_ALLOW_LOCAL` |
| Multi-worker deployment silently opens a fresh shell on reconnect | A user believes their session persisted when it did not | Single-worker self-host declared as the supported configuration for v1, the same posture the in-memory event bus already takes; the client surfaces a new-session notice |
| Zombie processes or leaked file descriptors | Resource exhaustion on a long-running server | Reap on disconnect, idle TTL, per-tenant cap, and a `waitpid` in teardown — each covered by a test |
| Terminal output logged somewhere and containing a secret | Credential disclosure with no redactor on the path | Never logged server-side; stated as a rule in the ADR and the docs |
| A stale terminal id resolves into another project | Commands run in the wrong tree | The project root is part of the server-side key, so it cannot; the client check makes the behavior visible rather than surprising |
| xterm bundle weight | Slower first load for every user, including those with the flag off | Dynamic import with `ssr: false`, so it is not in the main chunk |

## DoR / DoD

- **DoR:** E62-S3 and E11-S2 merged; the host-PTY ADR written and Accepted; the
  `terminal:use` scope added to the role map.
- **DoD:** all four story DoDs met; a session preserves directory and
  environment; Ctrl-C interrupts; the tab survives navigation; a project switch
  never reuses a session; the flag defaults off and `prod` refuses without an
  override; every allow audited; reference §14.4 corrected;
  `docs/execution/terminal.md` written; `docs/v2_platform/progress.md` updated.

## Affected documents and code

Documents: `docs/execution/terminal.md` (new), `docs/execution/shell.md`
(cross-reference), `docs/security.md`,
`docs/architecture/v2_platform_reference.md` §14.4, a new ADR under
`decisions/`, `docs/v2_platform/decisions/README.md`,
`docs/v2_platform/progress.md`, `CHANGELOG.md`.

Code: `backend/terminal/session.py` and `manager.py` (new),
`backend/api/routers/terminal_v2.py` (new), `backend/api/authorization.py`,
`backend/auth/` (role→scope map), `backend/config/settings.py`,
`backend/events/catalog.py`, `frontend/lib/terminal_socket.ts` (new),
`frontend/components/terminal/TerminalPanel.tsx` (new),
`frontend/components/shell/ExecutionPanelSlot.tsx`,
`frontend/components/shell/shellStore.ts`, `frontend/next.config.mjs`,
`frontend/package.json`, `frontend/locales/en.json`,
`frontend/locales/pt-BR.json`.
