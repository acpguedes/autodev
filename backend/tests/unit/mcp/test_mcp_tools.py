"""Tests for the MCP-to-agent-tool adapter and least-privilege enforcement (E9-S4-T2/T3)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from backend.agents.manifest import AgentManifest, validate_agent_manifest
from backend.agents.runtime import AgentRuntime, AgentRuntimeContext
from backend.agents.tools import AgentToolBroker, ToolAccessDenied
from backend.mcp.tools import McpServerConfig, McpToolProvider

_REFERENCE_SERVER_SOURCE = textwrap.dedent(
    """
    import json
    import sys


    def _send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()


    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        request = json.loads(raw_line)
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params") or {}
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "tools/list":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": [{"name": "echo"}, {"name": "slow"}]},
                }
            )
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"echoed": arguments, "tool": name}})
        else:
            _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "unknown method"}})
    """
)


@pytest.fixture
def reference_server_command(tmp_path: Path) -> list[str]:
    """Write the reference stdio MCP server script and return its argv."""
    script = tmp_path / "reference_mcp_server.py"
    script.write_text(_REFERENCE_SERVER_SOURCE, encoding="utf-8")
    return [sys.executable, str(script)]


def _manifest(tool_ids: tuple[str, ...], *, max_tool_calls: int | None = None) -> AgentManifest:
    """Build a valid agent manifest granting exactly ``tool_ids`` as tool permissions."""
    budgets = {"maxToolCalls": max_tool_calls} if max_tool_calls is not None else {}
    raw = {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": "acme/mcp-agent",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": "code.implementation", "version": "1.0.0"}],
        "io": {
            "contract": "acme/mcp-agent-io",
            "contractVersion": "1.0.0",
            "input": {
                "type": "object",
                "additionalProperties": False,
                "required": ["schemaVersion", "task"],
                "properties": {
                    "schemaVersion": {"const": "1.0.0"},
                    "task": {"type": "string", "minLength": 1},
                },
            },
            "output": {
                "type": "object",
                "additionalProperties": False,
                "required": ["schemaVersion", "status", "result"],
                "properties": {
                    "schemaVersion": {"const": "1.0.0"},
                    "status": {"enum": ["ok", "error"]},
                    "result": {"type": "string"},
                },
            },
        },
        "permissions": {"tools": list(tool_ids)},
        "budgets": budgets,
        "entrypoint": {"runtime": "python", "ref": "mcp_agent:Agent"},
    }
    result = validate_agent_manifest(raw)
    assert result.valid, result.errors
    assert result.manifest is not None
    return result.manifest


def _payload() -> dict[str, str]:
    """Build a minimal valid input payload matching the test manifest's input schema."""
    return {"schemaVersion": "1.0.0", "task": "use-mcp-tool"}


def test_provider_registers_only_allowlisted_tools(reference_server_command: list[str]) -> None:
    """Only allowlisted, server-advertised tool names are registered."""
    server = McpServerConfig(
        name="echo-server", transport="stdio", command=tuple(reference_server_command), allowlist=("echo",)
    )
    provider = McpToolProvider([server])

    try:
        tools = provider.connect()

        assert set(tools) == {"mcp:echo-server:echo"}
    finally:
        provider.close()


def test_provider_registers_nothing_for_a_server_with_empty_allowlist(reference_server_command: list[str]) -> None:
    """A server with no allowlist entries contributes zero tools (T3 deny-by-default)."""
    server = McpServerConfig(name="echo-server", transport="stdio", command=tuple(reference_server_command))
    provider = McpToolProvider([server])

    try:
        tools = provider.connect()

        assert tools == {}
    finally:
        provider.close()


def test_provider_skips_allowlisted_tool_the_server_does_not_offer(reference_server_command: list[str]) -> None:
    """An allowlisted name the server never advertises is silently skipped, not registered."""
    server = McpServerConfig(
        name="echo-server",
        transport="stdio",
        command=tuple(reference_server_command),
        allowlist=("echo", "does-not-exist"),
    )
    provider = McpToolProvider([server])

    try:
        tools = provider.connect()

        assert set(tools) == {"mcp:echo-server:echo"}
    finally:
        provider.close()


def test_broker_calls_allowlisted_mcp_tool_and_returns_its_result(reference_server_command: list[str]) -> None:
    """Calling an allowlisted, manifest-granted MCP tool via the broker returns its result."""
    server = McpServerConfig(
        name="echo-server", transport="stdio", command=tuple(reference_server_command), allowlist=("echo",)
    )
    with McpToolProvider([server]) as provider:
        manifest = _manifest(("mcp:echo-server:echo",))
        broker = AgentToolBroker(manifest, tools=provider.tools)

        result = broker.call_tool("mcp:echo-server:echo", value=42)

        assert result == {"echoed": {"value": 42}, "tool": "echo"}


def test_broker_denies_a_tool_not_granted_by_the_agent_manifest(reference_server_command: list[str]) -> None:
    """A tool registered by the provider but not granted in the manifest is not callable."""
    server = McpServerConfig(
        name="echo-server", transport="stdio", command=tuple(reference_server_command), allowlist=("echo",)
    )
    with McpToolProvider([server]) as provider:
        manifest = _manifest(())  # no tool permissions granted at all
        broker = AgentToolBroker(manifest, tools=provider.tools)

        with pytest.raises(ToolAccessDenied):
            broker.call_tool("mcp:echo-server:echo", value=1)


def test_broker_denies_a_tool_never_registered_by_the_server_allowlist(reference_server_command: list[str]) -> None:
    """A server-side tool excluded from its allowlist is neither registered nor callable,
    even if the agent manifest grants that tool id."""
    server = McpServerConfig(
        name="echo-server", transport="stdio", command=tuple(reference_server_command), allowlist=("echo",)
    )
    with McpToolProvider([server]) as provider:
        manifest = _manifest(("mcp:echo-server:slow",))  # granted, but never registered by the provider
        broker = AgentToolBroker(manifest, tools=provider.tools)

        assert "mcp:echo-server:slow" not in provider.tools
        with pytest.raises(ToolAccessDenied):
            broker.call_tool("mcp:echo-server:slow")


def test_mcp_tool_calls_consume_the_runtime_tool_call_budget(reference_server_command: list[str]) -> None:
    """Invoking an MCP tool through the Agent Runtime consumes the ``max_tool_calls`` budget."""
    server = McpServerConfig(
        name="echo-server", transport="stdio", command=tuple(reference_server_command), allowlist=("echo",)
    )
    with McpToolProvider([server]) as provider:
        manifest = _manifest(("mcp:echo-server:echo",), max_tool_calls=1)
        runtime = AgentRuntime(tools=provider.tools)

        def handler(ctx: AgentRuntimeContext) -> dict[str, str]:
            """Call the MCP tool twice, exceeding the manifest's tool-call budget."""
            ctx.call_tool("mcp:echo-server:echo", value=1)
            ctx.call_tool("mcp:echo-server:echo", value=2)
            return {"schemaVersion": "1.0.0", "status": "ok", "result": "unreachable"}

        result = runtime.run(manifest, _payload(), handler)

        assert result.status == "interrupted"
        assert result.stop_reason == "budget_exhausted"
        # The budget is charged for the call attempt itself, so the second
        # (over-budget) call still increments the counter before raising.
        assert result.metrics["tool.calls"] == 2
