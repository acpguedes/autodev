# ADR-032: Host PTY Terminal Behind a Fail-Closed Flag

- **Status:** Accepted
- **Date:** 2026-10-04
- **Authors:** AutoDev platform team
- **Related epic:** E65
- **Relates to:** E32 (hardened execution), ADR-018 (access audit), `AUTODEV_SANDBOX_ALLOW_LOCAL`

## Context

The platform had no interactive terminal. A usable one needs a pseudo-terminal
and a bidirectional transport. The E32 container (`--network=none`, read-only,
`--cap-drop=ALL`) is a batch surface: in it the user cannot install a
dependency, write a file, or keep a `cd`.

## Decision

1. **The PTY runs on the host**, as the server user, behind
   `AUTODEV_ENABLE_TERMINAL` (default off). Under the `prod` profile it also
   needs `AUTODEV_TERMINAL_ALLOW_PROD`; either gate missing means disabled.
2. The shell starts in the project root with an allowlisted environment
   (secret-store injections never reach it). **It does not confine the shell to
   the project**: a host shell can `cd` anywhere the server user can. Directory
   confinement needs real containment; `docker exec` into a long-lived
   per-project container is the eventual answer and is not built here.
3. Access needs the distinct `terminal:use` scope (maintainer tier and up).
   The WebSocket handshake is authorized and audited by `authorize_websocket`
   (`method="WEBSOCKET"`), because the app-level dependency cannot run on a
   handshake. Credentials never travel in URLs (`?token=` is rejected).
4. Sessions are keyed by `(tenant, project_root, terminal_id)`; the project root
   is server-resolved, so a session of another project is unreachable.
5. Terminal output is never logged or redacted server-side; lifecycle events
   (`terminal.session.opened`/`closed`) carry identifiers only.
6. The narrow `WS /v2/terminal/{id}` route is built instead of the general
   `WS /v2/ws` of reference §14.4, which stays unimplemented.
7. The frontend is corrected incrementally (xterm in the existing panel slot),
   not rebuilt.

## Consequences

- Largest privilege expansion of the Beta wave; mitigated by default-off, scope,
  audit and documentation.
- Single-worker deployments only: sessions are process-local.
