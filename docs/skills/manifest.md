# Skill Manifest (`skill.yaml`)

Canonical source: `docs/architecture/v2_platform_reference.md` Appendix D and
§18.6 (E6). Parser/validator: `backend/skills/manifest.py`.

## Fields

| Field | Type | Notes |
| --- | --- | --- |
| `schemaVersion` | string | Manifest schema version. |
| `id` | string | `namespace/name`, kebab-case. |
| `version` | string | SemVer `MAJOR.MINOR.PATCH`. |
| `name`, `description` | string | Human-readable. |
| `hostApi` | string | Supported host API version range. |
| `kind` | `deterministic \| llm-assisted` | Distinguishes execution model. |
| `entrypoint` | string | `module:function` reference. |
| `io.input`, `io.output` | object | Typed contract: `schemaVersion`, `type`, `required`, `properties`. |
| `permissions.filesystem` | `none \| read \| read-write` | Least-privilege, denied by default. |
| `permissions.network` | `none \| allow` | No network unless declared. |
| `permissions.sandbox` | boolean | Requires the hardened execution sandbox. |
| `dependencies` | list of `{id, version}` | SemVer-resolved via the Skill Registry. |
| `triggers` | list of strings | Exposes/suggests the skill for composition. |
| `budgets.timeoutSec`, `budgets.maxCostUsd` | number | Enforced on invocation. |

## Validation

`validate_manifest(raw: dict) -> ValidationResult` parses and validates a raw
document; `load_manifest(path)` reads a `skill.yaml` file from disk.
`validate_io(schema, payload) -> list[str]` checks a payload against an IO
contract (required keys present, declared properties only, primitive type
match) — deliberately dependency-free so it runs well under 20ms per call.

A runnable example is at `docs/v2_platform/templates/manifests/skill.yaml.example`.

## Registry

`backend/skills/registry_v2.py`'s `SkillRegistry` (mirrors `AgentRegistry`) persists
skill registrations and resolves them by SemVer range: `register(manifest, plugin_id=)`,
`resolve(id, version_range="*")`, `find_by_trigger(trigger)`, `deprecate(id, version,
reason)`, `list_skills()`, `catalog()`. `sync_from_plugin_store()` registers skills
declared via `skill` extension points in enabled plugins. Exposed at `/v2/skills`
(catalog), `/v2/skills/search?trigger=`, and `/v2/skills/{id}?version=` (`backend/api/routers/skills_v2.py`).
