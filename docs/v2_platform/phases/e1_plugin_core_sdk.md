# E1 — Plugin Core & SDK

**Wave:** Alpha
**Status:** Done · **Stories:** 5/5 complete
**Depends on:** E0
**Enables:** E2, E4, E6, E7-S4, E10-S4, E13
**Canonical source:** `docs/architecture/v2_platform_reference.md` §18.6 (E1), §18.8, §18.9

## Objective

Create the **Plugin Host** and the typed **extension points**, with manifest,
isolation, permissions, and a **SDK** (Python/TS) with first-class developer
experience (DX).

## Key result

An example plugin is discovered, loaded, isolated, and activated from `plugin.yaml`,
honoring its declared permissions, with a versioned contract (`hostApi`).

## Stories

### E1-S1 — `plugin.yaml` specification and extension points

**Status:** Done (2026-07-04)

Subtasks:
- `E1-S1-T1`: manifest JSON schema (id, version, `hostApi`, permissions, extension points).
- `E1-S1-T2`: typed catalog of extension points.
- `E1-S1-T3`: manifest validator.

| Criterion | Detail |
| --- | --- |
| Functional | Manifest with `namespace/name`, SemVer, and `hostApi` range validates/rejects correctly; unknown extension point is refused |
| Non-functional | Manifest validation < 50 ms; contract tests cover every declared extension point |
| DoR (specific) | Canonical v2 extension-point list agreed (RFC) |
| DoD (specific) | Schema published in the SDK; `docs/plugins/manifest.md` |
| Dependencies | E0-S1 |

### E1-S2 — Discovery and lifecycle (Plugin Host)

**Status:** Done (2026-07-04)

Subtasks:
- `E1-S2-T1`: discovery (directory/entry points).
- `E1-S2-T2`: install -> enable -> disable -> uninstall state machine.
- `E1-S2-T3`: version/`hostApi` compatibility resolution.

| Criterion | Detail |
| --- | --- |
| Functional | A plugin incompatible with `hostApi` is rejected with a reason; the lifecycle emits `plugin.installed`/`plugin.enabled`/`plugin.disabled` |
| Non-functional | Loading 50 plugins < 1 s; one plugin failing does not bring down the host (isolated failure) |
| DoR (specific) | Plugin event convention defined (§7) |
| DoD (specific) | State machine tested; Event Bus events documented |
| Dependencies | E1-S1, E0-S3 |

### E1-S3 — Isolation and permissions (least privilege)

**Status:** Done (2026-07-04)

Subtasks:
- `E1-S3-T1`: declared permission model (fs/net/exec/secrets).
- `E1-S3-T2`: import/execution sandbox.
- `E1-S3-T3`: broker mediating access.

| Criterion | Detail |
| --- | --- |
| Functional | A plugin without network permission cannot do network I/O; file access limited to granted paths; a violation is blocked and audited |
| Non-functional | Default denies everything (fail closed); broker overhead < 10%; no privilege escalation under adversarial testing |
| DoR (specific) | Permission taxonomy approved |
| DoD (specific) | Denial-by-permission test; audit via event; `docs/plugins/permissions.md` |
| Dependencies | E1-S2, E0-S4 |

### E1-S4 — SDK and DX (scaffolding)

**Status:** Done (2026-07-04)

Subtasks:
- `E1-S4-T1`: typed Python/TS contracts.
- `E1-S4-T2`: `sdk new plugin` CLI (scaffold).
- `E1-S4-T3`: contract-test harness for authors.

| Criterion | Detail |
| --- | --- |
| Functional | `sdk new plugin` generates a project that builds, runs, and passes contract tests; runnable examples included |
| Non-functional | Scaffold -> first green test < 5 min; contracts with SemVer-stable types |
| DoR (specific) | Minimal SDK surface defined |
| DoD (specific) | "Write your first plugin" guide in `docs/sdk/`; SDK published and versioned |
| Dependencies | E1-S1 |

### E1-S5 — Registry and resolution of active plugins

**Status:** Done (2026-07-04)

Subtasks:
- `E1-S5-T1`: index of plugins/inhabited extension points.
- `E1-S5-T2`: Control Plane query API.
- `E1-S5-T3`: safe hot-reload in dev.

| Criterion | Detail |
| --- | --- |
| Functional | The Control Plane lists active plugins and inhabited extension points; reloading in dev does not corrupt state |
| Non-functional | Registry query p95 < 100 ms; consistent after enable/disable |
| DoR (specific) | Registry read contract defined |
| DoD (specific) | `/v2` endpoint documented; hot-reload test |
| Dependencies | E1-S2 |

## v1 precursor / starting point

- The repository already has three informal "plugin seams" — auto-discovery of API
  routers (`backend/api/routers/__init__.py`), CLI plugins
  (`backend/cli_plugins/__init__.py`), and the agent registry
  (`backend/agents/registry.py`) — documented in `docs/architecture/plugin_seams.md`.
  This is drop-a-file auto-discovery, useful precedent for E1-S2's discovery
  mechanism, but it has **no manifest, no `hostApi` versioning, no declared
  permissions, and no isolation/sandbox** — the gap E1 as a whole closes.
- There is no SDK and no scaffolding tool today; E1-S4 starts from zero.

## Epic exit checklist

- [x] All 5 stories meet the global DoD (`../templates/dod_checklist.md`) plus their
      story-specific DoD above.
- [x] Contract tests green for every extension point declared in E1-S1's catalog.
- [x] `docs/v2_platform/progress.md` updated.
- [x] Alpha wave exit criteria this epic contributes to (§18.9) satisfied.
