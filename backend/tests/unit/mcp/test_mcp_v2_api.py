"""Tests for the ``POST /v2/mcp`` HTTP transport (E9-S4-T1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.routers.mcp_v2 import get_mcp_server
from backend.config.settings import reset_settings_cache
from backend.mcp.server import McpServer
from backend.persistence.database import DurableStore
from backend.skills.invoker import SkillInvocationBroker
from backend.skills.manifest import validate_manifest
from backend.skills.registry_v2 import SkillRegistry


def _sample_manifest_raw() -> dict[str, Any]:
    return {
        "schemaVersion": "1",
        "id": "autodev/skill-echo",
        "version": "1.0.0",
        "name": "Echo",
        "description": "Echoes back its input for MCP HTTP transport tests.",
        "hostApi": ">=2.0,<3.0",
        "kind": "deterministic",
        "entrypoint": "backend.tests.fixtures.mcp_echo_skill:echo",
        "io": {
            "input": {
                "schemaVersion": "1",
                "type": "object",
                "required": ["message"],
                "properties": {"message": {"type": "string"}},
            },
            "output": {
                "schemaVersion": "1",
                "type": "object",
                "required": ["message"],
                "properties": {"message": {"type": "string"}},
            },
        },
        "permissions": {"filesystem": "none", "network": "none", "sandbox": True},
        "budgets": {"timeoutSec": 5.0, "maxCostUsd": 0.0},
    }


def _build_server(tmp_path: Path) -> McpServer:
    store = DurableStore(f"sqlite:///{tmp_path / 'mcp-http-skills.db'}")
    registry = SkillRegistry(store)
    result = validate_manifest(_sample_manifest_raw())
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="autodev/plugin")
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    return McpServer(registry, broker, exposed_skills=["autodev/skill-echo"])


def test_initialize_over_http(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    app.dependency_overrides[get_mcp_server] = lambda: server
    try:
        response = TestClient(app).post("/v2/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    finally:
        app.dependency_overrides.pop(get_mcp_server, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == 1
    assert payload["result"]["serverInfo"]["name"] == "autodev"


def test_tools_list_over_http(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    app.dependency_overrides[get_mcp_server] = lambda: server
    try:
        response = TestClient(app).post("/v2/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    finally:
        app.dependency_overrides.pop(get_mcp_server, None)

    assert response.status_code == 200
    payload = response.json()
    tool_names = [tool["name"] for tool in payload["result"]["tools"]]
    assert tool_names == ["autodev/skill-echo"]


def test_tools_call_over_http(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    app.dependency_overrides[get_mcp_server] = lambda: server
    try:
        response = TestClient(app).post(
            "/v2/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "autodev/skill-echo", "arguments": {"message": "hi"}},
            },
        )
    finally:
        app.dependency_overrides.pop(get_mcp_server, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["isError"] is False
    assert "hi" in payload["result"]["content"][0]["text"]


def test_malformed_json_body_returns_json_rpc_parse_error(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    app.dependency_overrides[get_mcp_server] = lambda: server
    try:
        response = TestClient(app).post(
            "/v2/mcp",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
    finally:
        app.dependency_overrides.pop(get_mcp_server, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32700


def test_invalid_envelope_returns_json_rpc_invalid_request(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    app.dependency_overrides[get_mcp_server] = lambda: server
    try:
        response = TestClient(app).post("/v2/mcp", json={"jsonrpc": "1.0", "method": "initialize"})
    finally:
        app.dependency_overrides.pop(get_mcp_server, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32600


@pytest.fixture()
def token_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A TestClient with a stubbed MCP server, for bearer-token auth checks."""
    server = _build_server(tmp_path)
    app.dependency_overrides[get_mcp_server] = lambda: server
    reset_settings_cache()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_mcp_server, None)
    reset_settings_cache()


def test_no_token_configured_allows_mcp_requests(token_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTODEV_API_TOKEN", raising=False)
    response = token_client.post("/v2/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response.status_code == 200


def test_token_configured_rejects_missing_header(token_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTODEV_API_TOKEN", "s3cret")
    response = token_client.post("/v2/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response.status_code == 401


def test_token_configured_accepts_valid_bearer(token_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTODEV_API_TOKEN", "s3cret")
    response = token_client.post(
        "/v2/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert response.status_code == 200
