# ADR-015 — Global Installation Strategy

- **Status:** Accepted
- **Date:** 2026-07-17 (proposed) / 2026-08-18 (accepted)
- **Epic:** E34
- **Stories:** E34-S1..S3

## Context

The v2.0-beta gate now requires a documented, verified clean-environment
install (`v2_platform_reference.md` §18.9, criterion 12). E14 keeps the
`autodev` CLI command UX; E34 owns packaging, distribution, bootstrap and
upgrade. The mechanism must serve both "CLI on a dev machine" and
"self-hosted platform" without a repo checkout.

## Options

| Option | Pros | Cons |
| --- | --- | --- |
| pipx/uv tool from a published package | Idiomatic for a Python CLI; isolated env; trivial upgrades (`uv tool upgrade`) | Covers the CLI, not the platform services; requires a package index (or git ref) |
| Container bundle (compose/OCI images) | Whole-platform install incl. Postgres/MinIO; reproducible; matches production posture | Requires Docker; awkward for "just the CLI"; version skew between CLI and services must be managed |
| Installer script (curl \| sh style) | One command; can orchestrate both of the above | Highest maintenance surface; trust concerns; platform matrix testing burden |

## Decision

Hybrid, as recommended: a pipx/uv-installable package for the `autodev` CLI
plus a container bundle (`docker-compose`, already the platform's
production-posture substrate via `make container-up-full`) for the
self-hosted platform, with the CLI able to bootstrap and preflight-check the
bundle (E34-S2).

The mechanism is already strategy-agnostic in practice: `backend/pyproject.toml`'s
`[project.scripts] autodev = "backend.cli:main"` console-script entry point
is what `pip`, `pipx`, and `uv tool install` all consume identically — no
mechanism-specific code was needed to make this "the default option behind
a strategy-agnostic entry point" (E34-S1-T1). `backend/ops/version.py`
(E34-S1-T2) reports installed-package version plus best-effort commit/
build-date metadata via `autodev --version`, working the same whether the
package arrived via `pip install`, `pipx install`, or `uv tool install`.
`scripts/verify_clean_install.sh` (E34-S1-T3) proves the install path on a
machine with no repo checkout: it builds a wheel, installs it into a fresh
venv, and runs from a temp directory outside the repo.

No installer script (`curl | sh`) was built — the trust and platform-matrix
costs the options table calls out are not justified while `pip`/`pipx`/`uv`
already cover the documented path; this can be revisited if adoption
feedback demands it (unchanged from the original recommendation).

## Consequences

- E34-S1 shipped versioned packaging behind the existing strategy-agnostic
  console-script entry point — no new packaging mechanism was required, only
  version reporting and clean-install verification.
- E34-S2's bootstrap/preflight targets the container-bundle half of the
  hybrid (`docker-compose` `full` profile), documented as the self-host
  path in `docs/execution/cli-install.md`.
- Upgrade/compat work (E34-S3) binds to the E8-S4 backup contract, not to
  the install mechanism, per the original consequence.
- No open item remains for the E35-S3 open-decisions register — this ADR
  moved from Proposed to Accepted within E34 itself, before E34-S2 started,
  as required.

### E61 extension (2026-09-05)

E34 defined *how* `autodev` is installed; it did not define *where* the
tool's own state lives once installed. Running from a directory other than
the one the user happened to launch from left configuration and the default
database resolved relative to that launch directory
(`backend/config/runtime.py`, `backend/persistence/database.py`) — the
console-script mechanism itself was source-tree-independent, but the state
it read and wrote was not.

E61-S1 adds `AUTODEV_HOME` (default `~/.autodev`) as the one documented home
for configuration and data that belong to the tool rather than to one
project (`backend/config/paths.py`), and moves the *default* database and
`.env` lookup there and to the active project — never to this package's own
source tree, so a wheel install resolves them identically to an editable
checkout. E61-S2 composes the active configuration from internal defaults,
the global layer, and the per-project layer, governed by ADR-028. E61-S3
adds `make install-cli` (registering the `autodev` console script, which
`make install` alone never did) and extends
`scripts/verify_clean_install.sh` to prove a second install preserves the
global home's contents. No installation mechanism changed: the hybrid
console-script + container-bundle decision above stands unmodified.
