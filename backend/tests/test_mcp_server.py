"""Tests for the MCP dispatcher (E9-S4-T1, T3 least-privilege exposure)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Iterator

import pytest

from backend.mcp.jsonrpc import INVALID_PARAMS, METHOD_NOT_FOUND, JsonRpcRequest
from backend.mcp.server import PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION, McpServer
from backend.persistence.database import DurableStore
from backend.skills.invoker import SkillInvocationBroker
from backend.skills.manifest import validate_manifest
from backend.skills.registry_v2 import SkillRegistry

_MODULE_SOURCE = textwrap.dedent(
    """
    import socket  # noqa: F401 - only imported inside the denied-permission entrypoint

    def run_ok(repoRef):
        return {"testsPassed": True, "report": f"ran {repoRef}"}

    def run_network(repoRef):
        import socket  # deliberately unguarded import, denied without network permission
        return {"testsPassed": True, "report": socket.gethostname()}
    """
)


@pytest.fixture
def entrypoint_module(tmp_path: Path) -> Iterator[str]:
    """Write and import a throwaway module providing sample skill entrypoints."""
    (tmp_path / "sample_mcp_skill_mod.py").write_text(_MODULE_SOURCE, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        yield "sample_mcp_skill_mod"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("sample_mcp_skill_mod", None)


def _manifest_raw(skill_id: str, entrypoint: str) -> dict[str, object]:
    return {
        "schemaVersion": "1",
        "id": skill_id,
        "version": "1.0.0",
        "name": "Run Tests",
        "description": "Runs the test suite for a given repository reference.",
        "hostApi": ">=2.0,<3.0",
        "kind": "deterministic",
        "entrypoint": entrypoint,
        "io": {
            "input": {
                "schemaVersion": "1",
                "type": "object",
                "required": ["repoRef"],
                "properties": {"repoRef": {"type": "string"}},
            },
            "output": {
                "schemaVersion": "1",
                "type": "object",
                "required": ["testsPassed", "report"],
                "properties": {"testsPassed": {"type": "boolean"}, "report": {"type": "string"}},
            },
        },
        "permissions": {"filesystem": "none", "network": "none", "sandbox": True},
        "budgets": {"timeoutSec": 5.0, "maxCostUsd": 0.0},
    }


def _registry(tmp_path: Path, *raws: dict[str, object]) -> SkillRegistry:
    store = DurableStore(f"sqlite:///{tmp_path / 'mcp-skills.db'}")
    registry = SkillRegistry(store)
    for raw in raws:
        result = validate_manifest(raw)
        assert result.valid, result.errors
        assert result.manifest is not None
        registry.register(result.manifest, plugin_id="autodev/plugin")
    return registry


def _request(method: str, *, params: dict[str, object] | None = None, request_id: object = 1) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, id=request_id, params=params)  # type: ignore[arg-type]


def test_initialize_returns_protocol_metadata(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker, exposed_skills=[])

    response = server.handle(_request("initialize"))

    assert response.error is None
    assert response.result == {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "capabilities": {"tools": {}},
    }


def test_unknown_method_returns_method_not_found(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker, exposed_skills=[])

    response = server.handle(_request("bogus/method"))

    assert response.result is None
    assert response.error is not None
    assert response.error.code == METHOD_NOT_FOUND


def test_tools_list_only_returns_allowlisted_skills(entrypoint_module: str, tmp_path: Path) -> None:
    exposed_raw = _manifest_raw("autodev/skill-exposed", f"{entrypoint_module}:run_ok")
    hidden_raw = _manifest_raw("autodev/skill-hidden", f"{entrypoint_module}:run_ok")
    registry = _registry(tmp_path, exposed_raw, hidden_raw)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker, exposed_skills=["autodev/skill-exposed"])

    response = server.handle(_request("tools/list"))

    assert response.error is None
    tool_names = [tool["name"] for tool in response.result["tools"]]
    assert tool_names == ["autodev/skill-exposed"]


def test_tools_list_descriptor_has_input_schema(entrypoint_module: str, tmp_path: Path) -> None:
    raw = _manifest_raw("autodev/skill-exposed", f"{entrypoint_module}:run_ok")
    registry = _registry(tmp_path, raw)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker, exposed_skills=["autodev/skill-exposed"])

    response = server.handle(_request("tools/list"))

    tool = response.result["tools"][0]
    assert tool["name"] == "autodev/skill-exposed"
    assert tool["description"]
    assert tool["inputSchema"] == {
        "type": "object",
        "properties": {"repoRef": {"type": "string"}},
        "required": ["repoRef"],
    }


def test_tools_list_defaults_to_empty_when_no_allowlist(entrypoint_module: str, tmp_path: Path) -> None:
    raw = _manifest_raw("autodev/skill-exposed", f"{entrypoint_module}:run_ok")
    registry = _registry(tmp_path, raw)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker)  # no exposed_skills, no settings override -> empty allowlist

    response = server.handle(_request("tools/list"))

    assert response.result == {"tools": []}


def test_tools_call_invokes_allowlisted_skill(entrypoint_module: str, tmp_path: Path) -> None:
    raw = _manifest_raw("autodev/skill-exposed", f"{entrypoint_module}:run_ok")
    registry = _registry(tmp_path, raw)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker, exposed_skills=["autodev/skill-exposed"])

    response = server.handle(
        _request("tools/call", params={"name": "autodev/skill-exposed", "arguments": {"repoRef": "acme/repo"}})
    )

    assert response.error is None
    assert response.result["isError"] is False
    assert "acme/repo" in response.result["content"][0]["text"]


def test_tools_call_rejects_non_allowlisted_skill_as_tool_error(entrypoint_module: str, tmp_path: Path) -> None:
    exposed_raw = _manifest_raw("autodev/skill-exposed", f"{entrypoint_module}:run_ok")
    hidden_raw = _manifest_raw("autodev/skill-hidden", f"{entrypoint_module}:run_ok")
    registry = _registry(tmp_path, exposed_raw, hidden_raw)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker, exposed_skills=["autodev/skill-exposed"])

    response = server.handle(
        _request("tools/call", params={"name": "autodev/skill-hidden", "arguments": {"repoRef": "acme/repo"}})
    )

    assert response.error is None  # not a JSON-RPC protocol error
    assert response.result["isError"] is True
    assert "autodev/skill-hidden" in response.result["content"][0]["text"]


def test_tools_call_maps_invalid_input_to_tool_error(entrypoint_module: str, tmp_path: Path) -> None:
    raw = _manifest_raw("autodev/skill-exposed", f"{entrypoint_module}:run_ok")
    registry = _registry(tmp_path, raw)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker, exposed_skills=["autodev/skill-exposed"])

    response = server.handle(_request("tools/call", params={"name": "autodev/skill-exposed", "arguments": {}}))

    assert response.error is None
    assert response.result["isError"] is True


def test_tools_call_maps_permission_denied_to_tool_error(entrypoint_module: str, tmp_path: Path) -> None:
    raw = _manifest_raw("autodev/skill-network", f"{entrypoint_module}:run_network")
    registry = _registry(tmp_path, raw)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker, exposed_skills=["autodev/skill-network"])

    response = server.handle(
        _request("tools/call", params={"name": "autodev/skill-network", "arguments": {"repoRef": "acme/repo"}})
    )

    assert response.error is None  # PermissionDenied must not crash the dispatcher
    assert response.result["isError"] is True


def test_tools_call_requires_name_param(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    server = McpServer(registry, broker, exposed_skills=[])

    response = server.handle(_request("tools/call", params={}))

    assert response.result is None
    assert response.error is not None
    assert response.error.code == INVALID_PARAMS


def test_exposed_skills_reads_from_settings_when_not_overridden(tmp_path: Path) -> None:
    from backend.config.settings import Settings

    registry = _registry(tmp_path)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    settings = Settings(autodev_mcp_exposed_skills="autodev/skill-a, autodev/skill-b")
    server = McpServer(registry, broker, settings=settings)

    assert server.exposed_skills == frozenset({"autodev/skill-a", "autodev/skill-b"})
