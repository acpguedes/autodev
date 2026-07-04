from __future__ import annotations

import textwrap
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.agents.manifest import validate_agent_manifest
from backend.agents.registry_v2 import AGENT_REGISTRY_SCHEMA_VERSION, AgentRegistry
from backend.persistence.database import DurableStore
from backend.plugins.host import PluginHost


def _agent_manifest(
    agent_id: str = "acme/agent-coder",
    *,
    version: str = "1.0.0",
    capability: str = "code.implementation",
    level: str = "primary",
) -> dict[str, object]:
    return {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": agent_id,
        "version": version,
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": capability, "version": "1.0.0", "level": level}],
        "io": {
            "contract": "acme/coder-io",
            "contractVersion": "1.0.0",
            "input": {"type": "object", "additionalProperties": True},
            "output": {"type": "object", "additionalProperties": True},
        },
        "entrypoint": {"runtime": "python", "ref": "agent_coder:Agent"},
    }


def _validated_manifest(**kwargs):
    result = validate_agent_manifest(_agent_manifest(**kwargs))
    assert result.valid, result.errors
    assert result.manifest is not None
    return result.manifest


def test_registry_persists_multiple_versions_and_resolves_semver_ranges(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'agents.db'}")
    registry = AgentRegistry(store)
    registry.register(_validated_manifest(version="1.0.0"), plugin_id="acme/plugin")
    registry.register(_validated_manifest(version="1.2.0"), plugin_id="acme/plugin")
    registry.register(_validated_manifest(version="2.0.0"), plugin_id="acme/plugin")

    resolved = registry.resolve("acme/agent-coder", ">=1.0 <2.0")
    all_versions = registry.list_agents()

    assert resolved.version == "1.2.0"
    assert [ref.version for ref in all_versions] == ["2.0.0", "1.2.0", "1.0.0"]


def test_capability_search_returns_rankable_candidates_under_100ms(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'agents.db'}")
    registry = AgentRegistry(store)
    for index in range(120):
        registry.register(
            _validated_manifest(
                agent_id=f"acme/agent-{index}",
                version="1.0.0",
                capability="code.implementation",
                level="primary" if index == 5 else "secondary",
            ),
            plugin_id="acme/plugin",
        )

    started = time.perf_counter()
    candidates = registry.find_by_capability("code.implementation")
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms < 100
    assert candidates[0].agent_id == "acme/agent-5"
    assert candidates[0].score > candidates[-1].score


def test_deprecate_marks_version_and_signals_reason(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'agents.db'}")
    registry = AgentRegistry(store)
    registry.register(_validated_manifest(version="1.0.0"), plugin_id="acme/plugin")

    registry.deprecate("acme/agent-coder", "1.0.0", "superseded")

    deprecated = registry.resolve("acme/agent-coder", "==1.0.0")
    assert deprecated.deprecated is True
    assert deprecated.deprecation_reason == "superseded"


def test_registry_syncs_agent_manifests_from_enabled_plugin_host(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'agents.db'}")
    plugin_dir = tmp_path / "agent-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "agent_plugin.py").write_text(
        "def register(host):\n"
        "    host.register_extension('agent', 'acme/agent-plugin.agent', {'label': 'agent'})\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        textwrap.dedent(
            """
            schemaVersion: "1"
            id: "acme/agent-plugin"
            version: "0.1.0"
            hostApi: ">=2.0 <3.0"
            runtime:
              loader: "in-process"
              entrypoint: "agent_plugin:register"
            permissions: {}
            extensionPoints:
              - kind: "agent"
                id: "acme/agent-plugin.agent"
                contract: "^1.0"
                manifest: "./agent.yaml"
            """
        ).strip(),
        encoding="utf-8",
    )
    (plugin_dir / "agent.yaml").write_text(
        textwrap.dedent(
            """
            schemaVersion: "2.0"
            kind: Agent
            id: "acme/agent-plugin"
            version: "0.1.0"
            hostApi: ">=2.0 <3.0"
            capabilities:
              - id: "code.implementation"
                version: "1.0.0"
            io:
              contract: "acme/plugin-io"
              contractVersion: "1.0.0"
              input: {type: object, additionalProperties: true}
              output: {type: object, additionalProperties: true}
            entrypoint:
              runtime: python
              ref: "agent_plugin:Agent"
            """
        ).strip(),
        encoding="utf-8",
    )
    host = PluginHost(store=store)
    host.install(plugin_dir)
    host.enable("acme/agent-plugin")
    registry = AgentRegistry(store)

    registry.sync_from_plugin_store()

    assert registry.resolve("acme/agent-plugin", "*").plugin_id == "acme/agent-plugin"


def test_v2_agent_catalog_endpoint_returns_schema_version(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'agents.db'}")
    registry = AgentRegistry(store)
    registry.register(_validated_manifest(version="1.0.0"), plugin_id="acme/plugin")

    from backend.api.main import app
    from backend.api.routers.agents_v2 import get_agent_registry

    app.dependency_overrides[get_agent_registry] = lambda: registry
    try:
        response = TestClient(app).get("/v2/agents/catalog?capability=code.implementation")
    finally:
        app.dependency_overrides.pop(get_agent_registry, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["schemaVersion"] == AGENT_REGISTRY_SCHEMA_VERSION
    assert payload["agents"][0]["id"] == "acme/agent-coder"
    assert payload["agents"][0]["rank"]["score"] > 0
