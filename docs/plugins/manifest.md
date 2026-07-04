# Plugin Manifest

`plugin.yaml` is the required v2 descriptor for every plugin. The Plugin Host validates
it before import or activation.

Minimum fields:

```yaml
schemaVersion: "1"
id: "acme/example-plugin"
version: "0.1.0"
hostApi: ">=2.0 <3.0"
runtime:
  loader: "in-process"
  entrypoint: "example_plugin:register"
permissions: {}
extensionPoints:
  - kind: "skill"
    id: "acme/example-plugin.skill"
    contract: "^1.0"
    entrypoint: "example_plugin.skills:ExampleSkill"
```

Rules:

- `id` is `namespace/name` in kebab-case.
- `version` is SemVer `MAJOR.MINOR.PATCH`.
- `hostApi` is a compatibility range, normally `>=2.0 <3.0`.
- `runtime.loader` is `in-process`, `subprocess`, or `wasm`.
- Missing permissions grant nothing. Unknown permission blocks are refused.
- Each `extensionPoints[].kind` must be in the canonical catalog:
  `agent`, `skill`, `tool`, `reasoning`, `router`, `selector`, `evaluator`,
  `context_provider`, `retriever`, `validation_gate`, `ui_panel`, or `event_handler`.

The JSON schema is published at `backend/plugins/schemas/plugin.schema.json`. The Python
validator is `backend.plugins.validate_manifest`; it returns actionable validation
errors and is the same boundary the Plugin Host uses.
