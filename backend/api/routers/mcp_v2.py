"""v2 Control Plane API — MCP server transport over HTTP (E9-S4-T1).

Exposes ``POST /v2/mcp``: a single endpoint that accepts a JSON-RPC 2.0
request body and dispatches it through the same
:class:`~backend.mcp.server.McpServer` used by the stdio transport
(``backend.mcp.stdio_server``), so HTTP and stdio MCP clients share
identical tool exposure and least-privilege enforcement.

The request body is read as a raw JSON object (not a strict Pydantic model)
so malformed JSON-RPC envelopes are reported as JSON-RPC errors inside a
``200`` response — matching JSON-RPC-over-HTTP convention — rather than
FastAPI's generic ``422`` validation error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request

from backend.api.rbac_v2 import require_v2_principal
from backend.config.runtime import get_runtime_config_service
from backend.mcp.jsonrpc import (
    INVALID_REQUEST,
    PARSE_ERROR,
    JsonRpcInvalidRequestError,
    JsonRpcParseError,
    JsonRpcResponse,
    parse_request,
)
from backend.mcp.server import McpServer
from backend.skills.invoker import SkillInvocationBroker
from backend.skills.registry_v2 import SkillRegistry

router = APIRouter(prefix="/v2/mcp", tags=["mcp"], dependencies=[Depends(require_v2_principal)])


def get_mcp_server() -> McpServer:
    """Build an :class:`McpServer` bound to the current runtime config.

    Constructed fresh per request, matching the convention used by every
    other ``/v2`` router's service provider — routers must not import from
    ``backend.api.main`` (see ``backend/api/routers/__init__.py``'s
    auto-discovery convention).

    Returns:
        A new :class:`McpServer` wired to a fresh :class:`SkillRegistry` and
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


@router.post("")
async def call_mcp(request: Request, server: McpServer = Depends(get_mcp_server)) -> dict[str, Any]:
    """Dispatch a single JSON-RPC 2.0 MCP request over HTTP.

    Args:
        request: The raw HTTP request; its JSON body is parsed as a
            JSON-RPC 2.0 request object.
        server: MCP dispatcher dependency.

    Returns:
        The JSON-RPC response, whether success or error. Transport-level
        parse/validation failures (not valid JSON, or valid JSON that is not
        a valid JSON-RPC 2.0 request) are also returned as a JSON-RPC error
        response rather than raising an HTTP error status, matching
        JSON-RPC-over-HTTP convention.
    """
    body = await request.body()
    try:
        parsed = parse_request(body)
    except JsonRpcParseError as exc:
        return JsonRpcResponse.failure(None, PARSE_ERROR, str(exc)).to_dict()
    except JsonRpcInvalidRequestError as exc:
        return JsonRpcResponse.failure(None, INVALID_REQUEST, str(exc)).to_dict()
    return server.handle(parsed).to_dict()


__all__ = ["call_mcp", "get_mcp_server", "router"]
