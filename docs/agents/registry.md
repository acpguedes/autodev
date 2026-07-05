# Agent Registry

The v2 Agent Registry is the durable catalog of installed agent manifests. It stores
each `(agent id, version)` separately so multiple versions can coexist, resolves
SemVer ranges, and exposes capability search for selectors.

## Registration

`AgentRegistry.register(manifest, plugin_id=...)` persists the parsed `agent.yaml`
through the E0 store abstraction. The registry also syncs from the E1 Plugin Host:
enabled plugin records with an `agent` extension point and a `manifest` path are read
from the plugin store, then the referenced `agent.yaml` is validated and registered.

## Discovery

```python
registry.resolve("autodev/agent-coder", ">=1.0 <2.0")
registry.find_by_capability("code.implementation")
```

Capability results are rankable. Primary capability matches receive a higher score
than secondary matches, with SemVer used as a stable tiebreaker.

## API

`GET /v2/agents/catalog` returns all registered agents:

```json
{
  "schemaVersion": "2.0",
  "agents": []
}
```

`GET /v2/agents/catalog?capability=code.implementation` returns only matching
candidates with a `rank.score` field. Every response carries `schemaVersion`.

## Deprecation

`AgentRegistry.deprecate(id, version, reason)` marks a specific version as deprecated
without removing it. The registry emits an `agent.version.deprecated` event for audit
and keeps the version resolvable for compatibility.
