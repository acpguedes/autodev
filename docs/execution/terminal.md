# Interactive terminal (E65)

A real shell in the active project, from the execution panel's **Terminal** tab.

## Security: read this first

**An enabled terminal grants the caller the privileges of the AutoDev server
process.** It runs on the host, not in the E32 sandbox. Read it together with
`AUTODEV_SANDBOX_ALLOW_LOCAL`: both flags open host execution, and neither
confines a process to the project directory (the terminal only *starts* there).
For directory confinement, run AutoDev itself in a container or dedicated
account; per-project containers are future work (ADR-032).

- `AUTODEV_ENABLE_TERMINAL=1` enables it (default **off**; the tab is absent
  when off).
- Under `AUTODEV_PROFILE=prod` it additionally requires
  `AUTODEV_TERMINAL_ALLOW_PROD=1`; otherwise it stays disabled.
- Requires the `terminal:use` scope (maintainer role and above). Every allow is
  written to the access audit as `WEBSOCKET`.
- The shell environment is an allowlist (`PATH`, `HOME`, `USER`, `LANG`, ...);
  secret-store injections are not present.
- Terminal output is never logged or redacted by the server.

## Behavior

- `WS /v2/terminal/{terminal_id}` (cookie auth only; `?token=` is rejected).
  Closes `4401` unauthenticated, `4403` disabled/forbidden/over the session cap.
- Frames: client `input` / `resize`; server `info`, `output`, `exit`.
- Working directory and environment persist across commands; Ctrl-C interrupts.
- Sessions are keyed by tenant, project root and terminal id: switching project
  opens a new shell and the UI says so. Idle sessions are reaped after 30 min;
  4 sessions per tenant.
- Sessions are process-local: run a single worker.

`autodev --shell` is a different, non-PTY REPL (see [shell.md](shell.md)).
