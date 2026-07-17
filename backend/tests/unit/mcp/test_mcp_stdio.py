"""Tests for the stdio MCP transport (E9-S4-T1)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.mcp.server import McpServer
from backend.mcp.stdio_server import serve
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
        "description": "Echoes back its input for MCP stdio transport tests.",
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
    store = DurableStore(f"sqlite:///{tmp_path / 'mcp-stdio-skills.db'}")
    registry = SkillRegistry(store)
    result = validate_manifest(_sample_manifest_raw())
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="autodev/plugin")
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    return McpServer(registry, broker, exposed_skills=["autodev/skill-echo"])


def test_serve_roundtrips_requests_via_injected_streams(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "autodev/skill-echo", "arguments": {"message": "hi"}},
            }
        ),
    ]
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()

    serve(server, stdin=stdin, stdout=stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert len(responses) == 3
    assert responses[0]["result"]["serverInfo"]["name"] == "autodev"
    assert [tool["name"] for tool in responses[1]["result"]["tools"]] == ["autodev/skill-echo"]
    assert responses[2]["result"]["isError"] is False
    assert "hi" in responses[2]["result"]["content"][0]["text"]


def test_serve_skips_blank_lines(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    stdin = io.StringIO("\n   \n" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n\n")
    stdout = io.StringIO()

    serve(server, stdin=stdin, stdout=stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert len(responses) == 1
    assert responses[0]["id"] == 1


def test_serve_reports_parse_error_for_malformed_json(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    stdin = io.StringIO("{not-json\n")
    stdout = io.StringIO()

    serve(server, stdin=stdin, stdout=stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert responses[0]["error"]["code"] == -32700


def test_stdio_subprocess_roundtrip(tmp_path: Path) -> None:
    """Real end-to-end check: spawn ``python -m backend.mcp.stdio_server`` as a subprocess."""
    database_path = tmp_path / "stdio-subprocess.db"
    config_path = tmp_path / "autodev.config.json"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin_payload = "\n".join(json.dumps(request) for request in requests) + "\n"

    env = {
        "DATABASE_URL": f"sqlite:///{database_path}",
        "AUTODEV_CONFIG_PATH": str(config_path),
        "AUTODEV_PROJECT_ROOT": str(workspace),
        "LLM_PROVIDER": "stub",
        "PATH": "/usr/bin:/bin",
    }
    result = subprocess.run(
        [sys.executable, "-m", "backend.mcp.stdio_server"],
        input=stdin_payload,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[4]),
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    response_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(response_lines) == 2
    first = json.loads(response_lines[0])
    second = json.loads(response_lines[1])
    assert first["result"]["serverInfo"]["name"] == "autodev"
    assert second["result"] == {"tools": []}  # no AUTODEV_MCP_EXPOSED_SKILLS configured
