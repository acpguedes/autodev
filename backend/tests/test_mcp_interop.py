"""Cross-transport interop tests: real MCP client against the real MCP server.

E9-S4 epic-level check: :class:`~backend.mcp.client.McpStdioClient` (T2)
drives a subprocess running the actual server stack — ``McpServer`` +
``stdio_server.serve`` (T1) — over a genuine OS pipe boundary, exercising
both halves of the MCP integration together, including the least-privilege
allowlist (T3).
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any

from backend.mcp.client import McpStdioClient

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _echo_manifest() -> dict[str, Any]:
    """Build the raw manifest for the echo fixture skill.

    Returns:
        A valid skill manifest mapping for
        :func:`backend.tests.fixtures.mcp_echo_skill.echo`.
    """
    return {
        "schemaVersion": "1",
        "id": "autodev/skill-echo",
        "version": "1.0.0",
        "name": "Echo",
        "description": "Echoes back its input for MCP interop tests.",
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


_SERVER_SCRIPT = textwrap.dedent(
    """
    \"\"\"Interop fixture: run the real MCP server stack over stdio.\"\"\"

    import json
    import sys
    from pathlib import Path

    repo_root, workdir, exposed_json = sys.argv[1], sys.argv[2], sys.argv[3]
    sys.path.insert(0, repo_root)

    from backend.mcp.server import McpServer
    from backend.mcp.stdio_server import serve
    from backend.persistence.database import DurableStore
    from backend.skills.invoker import SkillInvocationBroker
    from backend.skills.manifest import validate_manifest
    from backend.skills.registry_v2 import SkillRegistry

    workspace = Path(workdir)
    store = DurableStore(f"sqlite:///{workspace / 'interop-skills.db'}")
    registry = SkillRegistry(store)
    manifest = json.loads((workspace / "manifest.json").read_text())
    result = validate_manifest(manifest)
    assert result.valid and result.manifest is not None, result.errors
    registry.register(result.manifest, plugin_id="autodev/plugin")
    broker = SkillInvocationBroker(registry, workspace=workspace)
    server = McpServer(registry, broker, exposed_skills=json.loads(exposed_json))
    serve(server, stdin=sys.stdin, stdout=sys.stdout)
    """
)


def _spawn_client(tmp_path: Path, exposed: list[str]) -> McpStdioClient:
    """Write the fixture server script and return a client that spawns it.

    Args:
        tmp_path: Scratch directory for the script, manifest, and skill DB.
        exposed: Skill ids to allowlist for MCP exposure (T3).

    Returns:
        An unstarted client configured to launch the fixture server.
    """
    script = tmp_path / "interop_server.py"
    script.write_text(_SERVER_SCRIPT)
    (tmp_path / "manifest.json").write_text(json.dumps(_echo_manifest()))
    command = [sys.executable, str(script), str(_REPO_ROOT), str(tmp_path), json.dumps(exposed)]
    return McpStdioClient(command, timeout_s=60.0)


def test_stdio_client_roundtrips_against_real_server(tmp_path: Path) -> None:
    """Initialize, discover, and invoke a skill end-to-end over stdio."""
    with _spawn_client(tmp_path, exposed=["autodev/skill-echo"]) as client:
        init = client.initialize()
        assert "protocolVersion" in init
        assert "serverInfo" in init

        tools = client.list_tools()
        assert [tool["name"] for tool in tools] == ["autodev/skill-echo"]
        assert "inputSchema" in tools[0]

        result = client.call_tool("autodev/skill-echo", {"message": "interop-olá"})
        assert result["isError"] is False
        payload = json.loads(result["content"][0]["text"])
        assert payload == {"message": "interop-olá"}


def test_non_exposed_skill_is_invisible_and_uncallable(tmp_path: Path) -> None:
    """An empty allowlist hides the skill and rejects calls (least privilege)."""
    with _spawn_client(tmp_path, exposed=[]) as client:
        client.initialize()
        assert client.list_tools() == []

        result = client.call_tool("autodev/skill-echo", {"message": "blocked"})
        assert result["isError"] is True
