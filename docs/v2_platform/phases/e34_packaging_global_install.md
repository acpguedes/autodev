# E34 — Packaging, Global Install & Self-Hosted Distribution

**Wave:** v2.0-beta — "plataforma completa em produção controlada".
**Status:** Not started · **Stories:** 0/3 complete
**Depends on:** E14 (`autodev` CLI story — E34 owns packaging/distribution,
E14 keeps CLI UX), E8 (persistence — embedded vs Postgres posture), E0
**Enables:** the v2.0-beta gate on clean-environment install, GA upgrade
path (E13), self-hosted adoption
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.9
(v2.0-beta); `docs/v2_platform/beta_gap_analysis.md`; ADR-015 (pending)

## Objective

Make AutoDev installable and upgradable as a product, not a repo checkout:
a **global installation strategy** whose mechanism is a documented, pending
decision (**ADR-015**: pipx/uv tool vs container bundle vs installer
script), a **self-host bootstrap** that stands up the platform with sane
defaults (including the embedded-vs-Postgres storage posture, documented,
not silently chosen), and a **versioned upgrade path** with migration
checks. E14's `autodev` CLI story keeps command UX; E34 owns how the CLI
and platform are packaged, distributed, installed and upgraded.

## Key result

On a clean machine, a documented one-command install yields a working
`autodev` CLI and a bootable platform; `autodev --version` reports a
released version; and upgrading between two versions preserves data with a
migration check — all verified in an environment with no repo checkout.

## Stories

### E34-S1 — Install strategy & packaging (ADR-015)

Subtasks:
- `E34-S1-T1`: ADR-015 lifecycle — options (pipx/uv tool from a published
  package, container bundle, installer script), trade-offs (dependency
  isolation, offline installs, WSL/macOS/Linux coverage), recommendation
  and pending decision; packaging implemented for the default option
  behind a strategy-agnostic entry point.
- `E34-S1-T2`: versioned artifact — reproducible build metadata (version,
  commit, build date) embedded and reported by `autodev --version`.
- `E34-S1-T3`: clean-environment install verification — documented steps
  validated on a machine without a repo checkout.

| Criterion | Detail |
| --- | --- |
| Functional | The documented install on a clean environment produces a working `autodev` CLI; `--version` reports build metadata; uninstall leaves no orphaned state |
| Non-functional | Install steps ≤ documented count; supported platforms listed with known limitations (e.g., WSL) |
| DoR (specific) | ADR-015 filed (may be `Proposed`); E14 CLI story scope boundary agreed |
| DoD (specific) | Clean-install verification recorded; `docs/execution/cli-install.md` extended with the packaging section |
| Dependencies | E14 (CLI), E0 |

### E34-S2 — Self-host bootstrap & storage posture

Subtasks:
- `E34-S2-T1`: bootstrap — a single documented command/config brings up the
  platform for self-host (services, migrations, first-run checks); secrets
  bootstrapped via E33 references, never inline plaintext.
- `E34-S2-T2`: storage posture — embedded (SQLite) vs Postgres documented
  as an explicit configuration with trade-offs (ADR-001 remains the default
  for production); no silent fallback between them.
- `E34-S2-T3`: preflight diagnostics — `autodev doctor`-style checks
  (ports, permissions, backends) with typed, actionable failures.

| Criterion | Detail |
| --- | --- |
| Functional | Bootstrap on a clean host reaches a usable platform; storage posture is explicit in config and reported by diagnostics; preflight failures are typed and actionable |
| Non-functional | Bootstrap idempotent (safe to re-run); defaults documented for self-hosters |
| DoR (specific) | E34-S1 packaging available; E33-S1 secret references available |
| DoD (specific) | Bootstrap + preflight tests; self-host section in install docs |
| Dependencies | E34-S1, E33-S1, E8 |

### E34-S3 — Upgrade & version compatibility

Subtasks:
- `E34-S3-T1`: upgrade path — versioned migrations gated by a
  compatibility check (refuse to run against newer schema; back up before
  migrate per E8 backup contract).
- `E34-S3-T2`: rollback posture — documented restore procedure using E8
  backup/RPO-RTO machinery; tested in staging scope.
- `E34-S3-T3`: release notes hook — upgrade surfaces the changelog for the
  target version; groundwork for the GA v1→v2 upgrade requirement (E13).

| Criterion | Detail |
| --- | --- |
| Functional | Upgrading between two consecutive versions preserves data and passes the compatibility check; downgrade attempts fail closed with the documented restore path |
| Non-functional | Upgrade duration bounded and documented for the reference dataset |
| DoR (specific) | E34-S2; E8-S4 backup contract reviewed |
| DoD (specific) | Upgrade/compat tests; upgrade section in install docs |
| Dependencies | E34-S2, E8-S4, E13 (GA path, additive) |

## Contracts & decisions

- **ADR-015 — Global installation strategy** (pending): options,
  trade-offs, recommendation documented; packaging entry point keeps the
  strategy swappable.
- Scope boundary: E14 keeps `autodev` CLI command UX; E34 owns packaging,
  distribution, bootstrap and upgrade.

## DoR / DoD

- **DoR:** ADR-015 filed; E14 CLI boundary agreed; gap analysis subsection
  approved.
- **DoD:** all story DoDs; install/upgrade docs published; v2.0-beta gate
  criteria (§18.9) reference E34 evidence; no push/PR without explicit
  authorization.
