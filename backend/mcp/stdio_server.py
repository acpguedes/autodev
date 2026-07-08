"""Stdio transport entrypoint for the MCP server (E9-S4-T1).

Runs as ``python -m backend.mcp.stdio_server``: reads line-delimited
JSON-RPC 2.0 requests from stdin, dispatches them through
:class:`~backend.mcp.server.McpServer`, and writes one JSON-RPC response per
line to stdout. All diagnostic output goes to stderr so stdout stays a
clean JSON-RPC stream, as MCP stdio clients expect.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TextIO

from backend.config.runtime import get_runtime_config_service
from backend.mcp.jsonrpc import (
    INVALID_REQUEST,
    PARSE_ERROR,
    JsonRpcInvalidRequestError,
    JsonRpcParseError,
    JsonRpcResponse,
    parse_request,
    write_line,
)
from backend.mcp.server import McpServer
from backend.skills.invoker import SkillInvocationBroker
from backend.skills.registry_v2 import SkillRegistry

logger = logging.getLogger(__name__)


def build_default_server() -> McpServer:
    """Construct an :class:`McpServer` bound to the process's runtime config.

    Returns:
        A new server wired to a fresh :class:`SkillRegistry` and
        :class:`SkillInvocationBroker` rooted at the configured project
        workspace, with the allowlist read from
        ``Settings().mcp_exposed_skills()``.
    """
    config_service = get_runtime_config_service()
    runtime_config = config_service.apply_to_environment()
    workspace = Path(runtime_config.repository.project_root)
    registry = SkillRegistry()
    registry.sync_from_plugin_store()
    broker = SkillInvocationBroker(registry, workspace=workspace)
    return McpServer(registry, broker)


def serve(server: McpServer, *, stdin: TextIO, stdout: TextIO) -> None:
    """Run the stdio read-dispatch-write loop until stdin is exhausted.

    Args:
        server: The dispatcher to route requests through.
        stdin: Line-delimited JSON-RPC input stream.
        stdout: Line-delimited JSON-RPC output stream. Flushed after every
            response so a client reading incrementally never blocks.
    """
    for line in stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            request = parse_request(stripped)
        except JsonRpcParseError as exc:
            response = JsonRpcResponse.failure(None, PARSE_ERROR, str(exc))
        except JsonRpcInvalidRequestError as exc:
            response = JsonRpcResponse.failure(None, INVALID_REQUEST, str(exc))
        else:
            response = server.handle(request)
        stdout.write(write_line(response) + "\n")
        stdout.flush()


def main() -> None:
    """Entrypoint for ``python -m backend.mcp.stdio_server``."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = build_default_server()
    serve(server, stdin=sys.stdin, stdout=sys.stdout)


if __name__ == "__main__":
    main()


__all__ = ["build_default_server", "main", "serve"]
