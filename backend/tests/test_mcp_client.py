"""Tests for the MCP client transports against a reference server (E9-S4-T2)."""

from __future__ import annotations

from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from backend.mcp.client import McpError, McpHttpClient, McpStdioClient

_REFERENCE_SERVER_SOURCE = textwrap.dedent(
    """
    import json
    import sys
    import time


    def _send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()


    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params") or {}
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"serverInfo": {"name": "reference"}}})
        elif method == "tools/list":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": [{"name": "echo"}, {"name": "slow"}, {"name": "garbage"}]},
                }
            )
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name == "echo":
                _send({"jsonrpc": "2.0", "id": req_id, "result": {"echoed": arguments}})
            elif name == "slow":
                time.sleep(2.0)
                _send({"jsonrpc": "2.0", "id": req_id, "result": {"echoed": arguments}})
            elif name == "garbage":
                sys.stdout.write("not-json-at-all\\n")
                sys.stdout.flush()
            else:
                _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "unknown tool"}})
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


def test_stdio_client_discovers_and_calls_a_tool(reference_server_command: list[str]) -> None:
    """``initialize`` -> ``list_tools`` -> ``call_tool`` all round-trip over stdio."""
    with McpStdioClient(reference_server_command, timeout_s=5.0) as client:
        client.initialize()
        tools = client.list_tools()

        assert {tool["name"] for tool in tools} == {"echo", "slow", "garbage"}

        result = client.call_tool("echo", {"value": 42})

        assert result == {"echoed": {"value": 42}}


def test_stdio_client_raises_mcp_error_on_timeout(reference_server_command: list[str]) -> None:
    """A slow server response past the per-call timeout raises ``McpError``, not a hang."""
    with McpStdioClient(reference_server_command, timeout_s=5.0) as client:
        client.initialize()

        with pytest.raises(McpError, match="did not respond"):
            client.call_tool("slow", timeout_s=0.2)


def test_stdio_client_raises_mcp_error_on_malformed_response(reference_server_command: list[str]) -> None:
    """A non-JSON line from the server yields ``McpError`` instead of hanging forever."""
    with McpStdioClient(reference_server_command, timeout_s=5.0) as client:
        client.initialize()

        with pytest.raises(McpError, match="malformed"):
            client.call_tool("garbage", timeout_s=5.0)


def test_stdio_client_close_is_idempotent(reference_server_command: list[str]) -> None:
    """Calling ``close`` more than once, or before ``start``, never raises."""
    client = McpStdioClient(reference_server_command, timeout_s=5.0)
    client.start()

    client.close()
    client.close()


def test_stdio_client_context_manager_starts_and_stops(reference_server_command: list[str]) -> None:
    """The client can be used as a context manager without calling ``start``/``close`` directly."""
    with McpStdioClient(reference_server_command, timeout_s=5.0) as client:
        assert client.initialize() == {"serverInfo": {"name": "reference"}}


class _JsonRpcHandler(BaseHTTPRequestHandler):
    """Minimal JSON-RPC 2.0 handler backing the local ephemeral HTTP test server."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - silence test server logging
        """Suppress default request logging noise during tests."""

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's required override name
        """Decode a JSON-RPC request body and dispatch to a toy handler."""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        request = json.loads(body)
        method = request.get("method")
        req_id = request.get("id")
        if method == "initialize":
            result: object = {"serverInfo": {"name": "reference-http"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "echo"}]}
        elif method == "tools/call":
            params = request.get("params") or {}
            result = {"echoed": params.get("arguments")}
        else:
            self._write({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "unknown method"}})
            return
        self._write({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _write(self, payload: dict[str, object]) -> None:
        """Serialize ``payload`` as the JSON HTTP response body."""
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def http_server_url() -> Iterator[str]:
    """Run a local ephemeral HTTP JSON-RPC server for the duration of a test."""
    server = HTTPServer(("127.0.0.1", 0), _JsonRpcHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_http_client_discovers_and_calls_a_tool(http_server_url: str) -> None:
    """``initialize`` -> ``list_tools`` -> ``call_tool`` all round-trip over HTTP."""
    with McpHttpClient(http_server_url, timeout_s=5.0) as client:
        client.initialize()
        tools = client.list_tools()

        assert {tool["name"] for tool in tools} == {"echo"}

        result = client.call_tool("echo", {"value": 1})

        assert result == {"echoed": {"value": 1}}


def test_http_client_raises_runtime_error_when_httpx_missing(
    monkeypatch: pytest.MonkeyPatch, http_server_url: str
) -> None:
    """``McpHttpClient`` raises a clear ``RuntimeError`` if ``httpx`` cannot be imported."""
    import builtins

    real_import = builtins.__import__

    def _no_httpx(name: str, *args: object, **kwargs: object) -> object:
        if name == "httpx":
            raise ImportError("simulated missing httpx")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _no_httpx)

    client = McpHttpClient(http_server_url, timeout_s=5.0)

    with pytest.raises(RuntimeError, match="httpx"):
        client.initialize()
