"""Unit tests filling coverage gaps in ``backend/mcp/stdio_server.py``.

Complements ``backend/tests/test_mcp_stdio.py`` (not modified here), which
already covers the happy-path roundtrip, blank-line skipping, the
``PARSE_ERROR`` branch, and a full subprocess end-to-end run. This file
targets the two branches that file does not reach in-process: ``serve()``'s
``JsonRpcInvalidRequestError``/``INVALID_REQUEST`` branch, and
``build_default_server()`` itself (only exercised indirectly there, via the
subprocess test).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Generator

import pytest

from backend.config.runtime import reset_runtime_config_cache
from backend.mcp.jsonrpc import INVALID_REQUEST
from backend.mcp.server import McpServer
from backend.mcp.stdio_server import build_default_server, serve
from backend.persistence.database import DurableStore, reset_store_cache
from backend.skills.invoker import SkillInvocationBroker
from backend.skills.registry_v2 import SkillRegistry


def _build_server(tmp_path: Path) -> McpServer:
    """Build a minimal, isolated :class:`McpServer` for direct ``serve()`` calls."""
    store = DurableStore(f"sqlite:///{tmp_path / 'mcp-stdio-gaps.db'}")
    registry = SkillRegistry(store)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)
    return McpServer(registry, broker)


# ---------------------------------------------------------------------------
# serve() — INVALID_REQUEST branch
# ---------------------------------------------------------------------------


def test_serve_reports_invalid_request_for_missing_jsonrpc_marker(tmp_path: Path) -> None:
    """A syntactically valid JSON object missing the ``"jsonrpc": "2.0"`` marker
    is reported as an ``INVALID_REQUEST`` (-32600) error, distinct from a parse
    error.
    """
    server = _build_server(tmp_path)
    stdin = io.StringIO(json.dumps({"id": 1, "method": "initialize"}) + "\n")
    stdout = io.StringIO()

    serve(server, stdin=stdin, stdout=stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert len(responses) == 1
    assert responses[0]["error"]["code"] == INVALID_REQUEST


def test_serve_reports_invalid_request_for_non_string_method(tmp_path: Path) -> None:
    """A request whose ``method`` is not a string is also an ``INVALID_REQUEST``."""
    server = _build_server(tmp_path)
    stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": 42}) + "\n")
    stdout = io.StringIO()

    serve(server, stdin=stdin, stdout=stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert responses[0]["error"]["code"] == INVALID_REQUEST


def test_serve_on_empty_stream_writes_nothing(tmp_path: Path) -> None:
    """``serve()`` against an empty stdin stream produces no output and does not raise."""
    server = _build_server(tmp_path)
    stdin = io.StringIO("")
    stdout = io.StringIO()

    serve(server, stdin=stdin, stdout=stdout)

    assert stdout.getvalue() == ""


# ---------------------------------------------------------------------------
# build_default_server()
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Isolate ``build_default_server()`` in its own database, config, and workspace."""
    database_path = tmp_path / "default-server.db"
    config_path = tmp_path / "autodev.config.json"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(workspace))
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    reset_store_cache()
    reset_runtime_config_cache()

    yield

    reset_store_cache()
    reset_runtime_config_cache()


def test_build_default_server_returns_wired_mcp_server() -> None:
    """``build_default_server()`` returns an :class:`McpServer` ready to ``serve()``."""
    server = build_default_server()

    assert isinstance(server, McpServer)


def test_build_default_server_result_handles_initialize(tmp_path: Path) -> None:
    """The server returned by ``build_default_server()`` answers ``initialize`` via ``serve()``."""
    server = build_default_server()
    stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n")
    stdout = io.StringIO()

    serve(server, stdin=stdin, stdout=stdout)

    response = json.loads(stdout.getvalue().splitlines()[0])
    assert response["result"]["serverInfo"]["name"] == "autodev"
