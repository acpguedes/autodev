# Paths and Configuration (E61)

> Story definition: `docs/v2_platform/phases/e61_global_install_layered_config.md`.
> Decisions: `docs/v2_platform/decisions/ADR-015-global-install-strategy.md`
> (installation mechanism), `docs/v2_platform/decisions/ADR-028-layered-configuration-semantics.md`
> (composition semantics).

`autodev` resolves every path that belongs to the *tool* — rather than to
one project — from a single global home, independently of the directory it
is launched from and of whether it runs from a repository checkout or an
installed wheel (`backend/config/paths.py`). This document is the reference
for those default locations and for how the active configuration is
composed.

## The global home

| Setting | Default | Override |
| --- | --- | --- |
| Global home | `~/.autodev/` | `AUTODEV_HOME` |
| Global configuration file | `<home>/autodev.config.json` | n/a — always `<home>/autodev.config.json` |
| Global data directory | `<home>/data/` | n/a — always `<home>/data` |
| Default state database | `<home>/data/autodev.db` | `DATABASE_URL` (wins unconditionally) |

Set `AUTODEV_HOME` once (e.g. in your shell profile) to relocate all four —
nothing else needs to change. `autodev doctor` reports whether the global
home exists and is writable (`global_home` check) and whether a pre-E61
`./autodev.db` sits beside the current directory unused (`legacy_database`
check, `backend/ops/doctor.py`).

## Per-project configuration

Each project has its own `autodev.config.json`, resolved the same way it was
before E61:

| Setting | Default | Override |
| --- | --- | --- |
| Project configuration file | `<project root>/autodev.config.json` | `AUTODEV_CONFIG_PATH` |
| Project root | the launch `cwd` | `AUTODEV_PROJECT_ROOT` |

Since E62 a project is also a directory with a `.autodev/` marker, found by an
ancestor-directory walk; see [`docs/projects/discovery.md`](../projects/discovery.md).
Its `.autodev/config.json` is an additional layer between the global layer and
the project's `autodev.config.json` (composition: defaults → global →
`.autodev/config.json` → `autodev.config.json`).

## Composition: defaults → global → project

The active `RuntimeConfig` (LLM provider settings, repository settings) is
composed from three layers, deep-merged **per field**, lowest priority
first:

1. **Internal defaults** — `RuntimeConfig`'s own field defaults, with a
   handful seeded from environment variables for backward compatibility
   (`LLM_PROVIDER`, `OPENAI_MODEL`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`,
   `OPENAI_TEMPERATURE`, `AUTODEV_PROJECT_ROOT`).
2. **Global configuration** — `<AUTODEV_HOME>/autodev.config.json`, shared
   by every project on the machine.
3. **Project configuration** — the project's own `autodev.config.json`.

A project file that sets only one field (say, `llm.model`) inherits every
other field — `llm.provider`, `llm.base_url`, `repository.repository_label`,
and so on — from the global layer, which in turn inherits from the internal
defaults. There is no "all or nothing": each field is resolved
independently.

```json
// ~/.autodev/autodev.config.json (global)
{"llm": {"provider": "openai", "model": "gpt-4o", "base_url": "https://api.openai.com/v1"}}
```

```json
// <project>/autodev.config.json (project)
{"llm": {"model": "gpt-4o-mini"}}
```

resolves to `provider=openai`, `model=gpt-4o-mini` (project wins),
`base_url=https://api.openai.com/v1` (inherited from global).

### Absence vs. falsiness (ADR-028)

**A layer contributes a field only when that field's key is present in its
JSON document.** A present key's value — including `""`, and by the same
rule a future `false` or `0` — always wins over a lower layer and is never
replaced by a default merely because it is falsy. Before E61-S2, an empty
string was silently collapsed back to that field's default
(`value.strip() or <default>`); that was the defect ADR-028 fixes, not a
contract this changes. If you want an explicitly empty `repository_label`,
set `"repository_label": ""` in the project file and it stays empty.

### Writes are layer-scoped

Saving a configuration (`PUT /config`, `PUT /v2/config`,
`PUT /v2/provider-config`, or `autodev config set`) always writes to the
**project** layer, and only the fields that differ from what the
defaults+global layers would already produce. A value already provided by
the global layer — an API key in particular — is never duplicated into the
project file merely because the save request's full, materialized
configuration happens to carry it. There is currently no API/CLI surface for
writing the *global* layer; edit `<AUTODEV_HOME>/autodev.config.json`
directly (it is created `0600` since it may hold an LLM API key).

### Invalid files

A configuration file that exists but is not valid JSON, is not a JSON
object, or fails `RuntimeConfig` validation once composed raises
`backend.config.runtime.ConfigFileError`, naming the offending file's path
and the problem. It is never silently treated as if the file were absent —
only a genuinely *missing* file (the common case) contributes nothing and
lets lower layers take over.

## Changing the defaults

| To change | Set |
| --- | --- |
| Where the tool's own state lives | `AUTODEV_HOME` |
| The state database (overrides the global-home default unconditionally) | `DATABASE_URL` |
| The project configuration file's path | `AUTODEV_CONFIG_PATH` |
| The project root used to resolve the project configuration file | `AUTODEV_PROJECT_ROOT` |
| The declarative settings file (`backend.config.settings.Settings`, a separate, env-first layer covering persistence, observability, security, and more) | `AUTODEV_SETTINGS_FILE` |

`AUTODEV_SETTINGS_FILE` and `AUTODEV_CONFIG_PATH`/`AUTODEV_HOME` are
deliberately separate mechanisms: `Settings` (`backend/config/settings.py`)
is the declarative, mostly-operator-facing configuration (ports, database
pooling, observability, auth) with a fixed env → file → dotenv precedence;
`RuntimeConfig` (`backend/config/runtime.py`, this document's main subject)
is the smaller, UI/CLI-editable surface (LLM provider, repository root) with
the three-layer composition described above.
