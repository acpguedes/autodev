# ADR-015 — Global Installation Strategy

- **Status:** Proposed (decision pending — do not resolve silently)
- **Date:** 2026-07-17
- **Epic:** E34
- **Stories:** E34-S1..S3 (implementable behind the entry point while pending)
- **Decide by:** before E34-S2 starts

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

## Recommendation (not a decision)

Hybrid: pipx/uv-published package for the `autodev` CLI plus a container
bundle for the self-hosted platform, with the CLI able to bootstrap the
bundle (`E34-S2` preflight). An installer script only as a thin wrapper if
adoption feedback demands it.

## Consequences (of the pending state)

- E34-S1 ships versioned packaging behind a strategy-agnostic entry point;
  the clean-install verification defines the acceptance regardless of
  mechanism.
- Upgrade/compat work (E34-S3) binds to the E8-S4 backup contract, not to
  the install mechanism.
- Tracked in the E35-S3 open-decisions register with owner and milestone.
