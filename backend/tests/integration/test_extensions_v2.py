"""Contract tests for the unified ``/v2/extensions`` catalog (E16-S4)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from backend.agents.manifest import validate_agent_manifest
from backend.agents.registry_v2 import AgentRegistry
from backend.api.routers.extensions_v2 import (
    get_active_plugin_registry,
    get_agent_registry,
    get_plugin_host,
    get_skill_registry,
)
from backend.config.settings import reset_settings_cache
from backend.persistence.database import DurableStore
from backend.plugins.host import PluginHost
from backend.plugins.registry import ActivePluginRegistry
from backend.skills.manifest import validate_manifest as validate_skill_manifest
from backend.skills.registry_v2 import SkillRegistry


def _agent_manifest_raw(agent_id: str = "acme/agent-coder", *, version: str = "1.0.0") -> dict[str, object]:
    """Build a minimal, valid raw agent manifest document."""
    return {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": agent_id,
        "version": version,
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": "code.implementation", "version": "1.0.0", "level": "primary"}],
        "io": {
            "contract": "acme/coder-io",
            "contractVersion": "1.0.0",
            "input": {"type": "object", "additionalProperties": True},
            "output": {"type": "object", "additionalProperties": True},
        },
        "entrypoint": {"runtime": "python", "ref": "agent_coder:Agent"},
    }


def _skill_manifest_raw(skill_id: str = "acme/skill-run-tests", *, version: str = "1.0.0") -> dict[str, object]:
    """Build a minimal, valid raw skill manifest document."""
    return {
        "schemaVersion": "1",
        "id": skill_id,
        "version": version,
        "hostApi": ">=2.0,<3.0",
        "kind": "deterministic",
        "entrypoint": "autodev_skills.testing:run_tests",
        "io": {
            "input": {"schemaVersion": "1", "type": "object", "required": [], "properties": {}},
            "output": {"schemaVersion": "1", "type": "object", "required": [], "properties": {}},
        },
        "permissions": {"filesystem": "read", "network": "none", "sandbox": True},
        "triggers": ["code.after-edit"],
    }


def _write_plugin(root: Path, *, plugin_id: str = "acme/catalog-plugin") -> Path:
    """Write a minimal plugin project registering a skill extension point."""
    plugin_dir = root / "catalog-plugin"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "catalog_plugin.py").write_text(
        f'def register(host):\n    host.register_extension("skill", "{plugin_id}.skill", {{"label": "v1"}})\n',
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        textwrap.dedent(
            f"""
            schemaVersion: "1"
            id: "{plugin_id}"
            version: "0.1.0"
            hostApi: ">=2.0 <3.0"
            runtime:
              loader: "in-process"
              entrypoint: "catalog_plugin:register"
            permissions: {{}}
            extensionPoints:
              - kind: "skill"
                id: "{plugin_id}.skill"
                contract: "^1.0"
            """
        ).strip(),
        encoding="utf-8",
    )
    return plugin_dir


@pytest.fixture()
def seeded_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[dict[str, object], None, None]:
    """A TestClient wired to an isolated store pre-seeded with one agent, skill, and plugin.

    Overrides ``extensions_v2``'s dependency getters directly, mirroring the
    pattern in ``backend/tests/test_agents_v2_registry.py`` and
    ``backend/tests/test_plugins_registry_api.py`` — no LLM/session machinery
    is exercised, so the heavier ``/v2` API contract fixture is unnecessary.
    """
    monkeypatch.delenv("AUTODEV_MCP_EXPOSED_SKILLS", raising=False)
    reset_settings_cache()

    store = DurableStore(f"sqlite:///{tmp_path / 'extensions.db'}")
    agent_registry = AgentRegistry(store)
    skill_registry = SkillRegistry(store)
    plugin_registry = ActivePluginRegistry(store)
    plugin_host = PluginHost(store=store)

    agent_result = validate_agent_manifest(_agent_manifest_raw())
    assert agent_result.valid, agent_result.errors
    assert agent_result.manifest is not None
    agent_registry.register(agent_result.manifest, plugin_id="acme/plugin")

    skill_result = validate_skill_manifest(_skill_manifest_raw())
    assert skill_result.valid, skill_result.errors
    assert skill_result.manifest is not None
    skill_registry.register(skill_result.manifest, plugin_id="acme/plugin")

    plugin_dir = _write_plugin(tmp_path)
    plugin_host.install(plugin_dir)
    plugin_host.enable("acme/catalog-plugin")

    monkeypatch.setenv("AUTODEV_MCP_EXPOSED_SKILLS", "acme/skill-run-tests")
    reset_settings_cache()

    from backend.api.main import app

    app.dependency_overrides[get_agent_registry] = lambda: agent_registry
    app.dependency_overrides[get_skill_registry] = lambda: skill_registry
    app.dependency_overrides[get_active_plugin_registry] = lambda: plugin_registry
    app.dependency_overrides[get_plugin_host] = lambda: plugin_host
    try:
        yield {
            "client": TestClient(app),
            "agent_registry": agent_registry,
            "skill_registry": skill_registry,
            "plugin_host": plugin_host,
        }
    finally:
        app.dependency_overrides.pop(get_agent_registry, None)
        app.dependency_overrides.pop(get_skill_registry, None)
        app.dependency_overrides.pop(get_active_plugin_registry, None)
        app.dependency_overrides.pop(get_plugin_host, None)
        reset_settings_cache()


class TestUnifiedCatalog:
    """``GET /v2/extensions`` aggregates agents, skills, plugins, and MCP servers."""

    def test_catalog_returns_all_four_kinds_with_schema_version(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        response = client.get("/v2/extensions", params={"limit": 100})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        kinds = {item["kind"] for item in body["items"]}
        assert kinds == {"agent", "skill", "plugin", "mcp"}
        assert body["page"]["total"] == len(body["items"])

    def test_catalog_kind_filter(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        response = client.get("/v2/extensions", params={"kind": "plugin"})
        assert response.status_code == 200
        body = response.json()
        assert all(item["kind"] == "plugin" for item in body["items"])
        assert body["items"][0]["id"] == "acme/catalog-plugin"

    def test_mcp_item_reflects_allowlist(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        response = client.get("/v2/extensions", params={"kind": "mcp"})
        mcp_items = response.json()["items"]
        assert mcp_items[0]["id"] == "acme/skill-run-tests"
        assert mcp_items[0]["enabled"] is True


class TestEnableDisableDelegation:
    """Enable/disable delegates to each subsystem's own activation mechanism."""

    def test_agent_disable_then_enable_round_trip(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        agent_registry: AgentRegistry = seeded_client["agent_registry"]  # type: ignore[assignment]

        disable_response = client.post("/v2/extensions/agent/acme%2Fagent-coder/disable")
        assert disable_response.status_code == 200
        assert disable_response.json()["item"]["enabled"] is False
        assert agent_registry.resolve("acme/agent-coder", "*").deprecated is True

        enable_response = client.post("/v2/extensions/agent/acme%2Fagent-coder/enable")
        assert enable_response.status_code == 200
        assert enable_response.json()["item"]["enabled"] is True
        assert agent_registry.resolve("acme/agent-coder", "*").deprecated is False

    def test_agent_disable_unknown_returns_standard_error_envelope(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        response = client.post("/v2/extensions/agent/acme%2Fno-such-agent/disable")
        assert response.status_code == 404
        assert response.json()["detail"]["schemaVersion"] == "2.0"

    def test_plugin_disable_then_enable_delegates_to_plugin_host(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        plugin_host: PluginHost = seeded_client["plugin_host"]  # type: ignore[assignment]

        disable_response = client.post("/v2/extensions/plugin/acme%2Fcatalog-plugin/disable")
        assert disable_response.status_code == 200
        assert disable_response.json()["item"]["enabled"] is False
        assert plugin_host.get("acme/catalog-plugin").state.value == "disabled"

        enable_response = client.post("/v2/extensions/plugin/acme%2Fcatalog-plugin/enable")
        assert enable_response.status_code == 200
        assert enable_response.json()["item"]["enabled"] is True
        assert plugin_host.get("acme/catalog-plugin").state.value == "enabled"

    def test_mcp_disable_removes_skill_from_allowlist(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        response = client.post("/v2/extensions/mcp/acme%2Fskill-run-tests/disable")
        assert response.status_code == 200
        assert response.json()["item"]["enabled"] is False
        from backend.config.settings import get_settings

        assert "acme/skill-run-tests" not in get_settings().mcp_exposed_skills()

    def test_skill_disable_then_enable_round_trip(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        skill_registry: SkillRegistry = seeded_client["skill_registry"]  # type: ignore[assignment]

        disable_response = client.post("/v2/extensions/skill/acme%2Fskill-run-tests/disable")
        assert disable_response.status_code == 200
        assert disable_response.json()["item"]["enabled"] is False
        assert skill_registry.resolve("acme/skill-run-tests", "*").deprecated is True


class TestAgentCreateEdit:
    """``PUT``/``GET /v2/extensions/agents/{agent_id}`` create/edit agent extensions."""

    def test_create_agent_persists_system_prompt_model_and_tools(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        payload = {
            "version": "1.0.0",
            "displayName": "Custom Reviewer",
            "description": "Reviews diffs.",
            "systemPrompt": "You are a careful reviewer.",
            "model": "gpt-4o-mini",
            "allowedTools": ["read_file", "search_code"],
        }
        response = client.put("/v2/extensions/agents/acme%2Fcustom-reviewer", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["systemPrompt"] == "You are a careful reviewer."
        assert body["model"] == "gpt-4o-mini"
        assert body["allowedTools"] == ["read_file", "search_code"]
        assert body["item"]["id"] == "acme/custom-reviewer"

        get_response = client.get("/v2/extensions/agents/acme%2Fcustom-reviewer")
        assert get_response.status_code == 200
        assert get_response.json()["systemPrompt"] == "You are a careful reviewer."

    def test_edit_existing_agent_overwrites_fields(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        base_payload = {"version": "1.0.0", "systemPrompt": "First prompt", "model": "gpt-4o-mini", "allowedTools": []}
        client.put("/v2/extensions/agents/acme%2Feditable-agent", json=base_payload).raise_for_status()

        updated_payload = {"version": "1.0.0", "systemPrompt": "Second prompt", "model": "gpt-4o", "allowedTools": ["read_file"]}
        response = client.put("/v2/extensions/agents/acme%2Feditable-agent", json=updated_payload)
        assert response.status_code == 200
        body = response.json()
        assert body["systemPrompt"] == "Second prompt"
        assert body["model"] == "gpt-4o"
        assert body["allowedTools"] == ["read_file"]

    def test_create_agent_rejects_invalid_manifest(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        payload = {"version": "not-a-semver", "systemPrompt": "", "model": "gpt-4o-mini", "allowedTools": []}
        response = client.put("/v2/extensions/agents/acme%2Finvalid-agent", json=payload)
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["schemaVersion"] == "2.0"
        assert detail["error"]["code"] == 400

    def test_get_unknown_agent_returns_standard_error_envelope(self, seeded_client: dict[str, object]) -> None:
        client: TestClient = seeded_client["client"]  # type: ignore[assignment]
        response = client.get("/v2/extensions/agents/acme%2Fno-such-agent")
        assert response.status_code == 404
        assert response.json()["detail"]["schemaVersion"] == "2.0"
