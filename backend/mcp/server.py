"""Transport-agnostic MCP dispatcher exposing platform skills as MCP tools.

Implements the small MCP method surface needed to expose the Skill Registry
(`backend.skills.registry_v2.SkillRegistry`) to MCP clients: ``initialize``,
``tools/list``, and ``tools/call`` (E9-S4-T1). Every skill invocation is
routed through the existing least-privilege
:class:`~backend.skills.invoker.SkillInvocationBroker`, so permission
enforcement, input/output validation, and timeout budgets are reused
verbatim rather than reimplemented.

T3 (least-privilege mapping): only skills explicitly allowlisted for MCP
exposure — via the constructor's ``exposed_skills`` or the
``AUTODEV_MCP_EXPOSED_SKILLS`` setting (comma-separated skill ids, empty by
default) — are listed by ``tools/list`` or callable via ``tools/call``.
Every other registered skill stays invisible and unreachable through this
server, regardless of what the Skill Registry otherwise contains.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any, Callable

from backend.config.settings import Settings, get_settings
from backend.mcp.jsonrpc import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    JsonRpcRequest,
    JsonRpcResponse,
)
from backend.plugins.permissions import PermissionDenied
from backend.skills.invoker import SkillBudgetExceeded, SkillInvocationBroker, SkillInvocationDenied
from backend.skills.manifest import SkillIOSchema, SkillManifest
from backend.skills.registry_v2 import SkillRegistry

logger = logging.getLogger(__name__)

#: MCP protocol version advertised by ``initialize``.
PROTOCOL_VERSION = "2025-06-18"
#: Name advertised in ``initialize``'s ``serverInfo``.
SERVER_NAME = "autodev"
#: Version advertised in ``initialize``'s ``serverInfo``.
SERVER_VERSION = "0.3.0"


class McpInvalidParamsError(ValueError):
    """Raised when a method's ``params`` do not match its expected shape.

    Mapped by :meth:`McpServer.handle` to a JSON-RPC error response with
    code :data:`backend.mcp.jsonrpc.INVALID_PARAMS`.
    """


def _io_schema_to_json_schema(io_schema: SkillIOSchema) -> dict[str, Any]:
    """Translate a skill's simplified :class:`SkillIOSchema` into JSON Schema.

    Args:
        io_schema: The skill's declared input (or output) IO contract.

    Returns:
        A JSON-Schema-shaped mapping suitable for an MCP tool's ``inputSchema``.
    """
    schema: dict[str, Any] = {"type": io_schema.type}
    if io_schema.type == "object":
        schema["properties"] = {name: dict(descriptor) for name, descriptor in io_schema.properties.items()}
        if io_schema.required:
            schema["required"] = list(io_schema.required)
    return schema


def _tool_descriptor(manifest: SkillManifest) -> dict[str, Any]:
    """Build an MCP tool descriptor for a registered skill.

    Args:
        manifest: The skill's parsed manifest.

    Returns:
        A mapping with ``name``, ``description``, and ``inputSchema`` keys.
    """
    return {
        "name": manifest.id,
        "description": manifest.description,
        "inputSchema": _io_schema_to_json_schema(manifest.io_input),
    }


def _text_result(text: str, *, is_error: bool) -> dict[str, Any]:
    """Build an MCP ``tools/call`` result in the standard content/isError shape.

    Args:
        text: The textual content to surface to the MCP client.
        is_error: Whether the tool invocation failed.

    Returns:
        A mapping with ``content`` (a single text block) and ``isError``.
    """
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _stringify(value: Any) -> str:
    """Render a skill's output payload as MCP text content.

    Args:
        value: The skill's (already IO-validated) output value.

    Returns:
        ``value`` unchanged if it is already a string, else its JSON
        serialization.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value)


class McpServer:
    """Dispatches JSON-RPC 2.0 MCP requests over the platform's Skill Registry."""

    def __init__(
        self,
        registry: SkillRegistry,
        broker: SkillInvocationBroker,
        *,
        exposed_skills: Iterable[str] | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialize the dispatcher.

        Args:
            registry: Skill Registry used to resolve skill manifests for
                ``tools/list`` descriptors.
            broker: Least-privilege invocation broker used to execute
                ``tools/call`` requests.
            exposed_skills: Explicit allowlist of skill ids to expose via
                MCP. When ``None`` (the default), falls back to
                ``settings.mcp_exposed_skills()`` — empty unless
                ``AUTODEV_MCP_EXPOSED_SKILLS`` is configured, meaning no
                skill is exposed until explicitly allowlisted.
            settings: Settings instance to read the allowlist from when
                ``exposed_skills`` is not given. Defaults to the process-wide
                cached settings.
        """
        self._registry = registry
        self._broker = broker
        if exposed_skills is not None:
            self._exposed = frozenset(exposed_skills)
        else:
            resolved_settings = settings if settings is not None else get_settings()
            self._exposed = frozenset(resolved_settings.mcp_exposed_skills())
        self._methods: dict[str, Callable[[JsonRpcRequest], Any]] = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
        }

    @property
    def exposed_skills(self) -> frozenset[str]:
        """The allowlisted skill ids this server exposes via MCP."""
        return self._exposed

    def handle(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """Dispatch a single JSON-RPC request to its MCP method handler.

        Args:
            request: The parsed JSON-RPC request.

        Returns:
            The JSON-RPC response. Unknown methods yield a
            :data:`~backend.mcp.jsonrpc.METHOD_NOT_FOUND` error; malformed
            params yield :data:`~backend.mcp.jsonrpc.INVALID_PARAMS`; any
            other unexpected failure yields
            :data:`~backend.mcp.jsonrpc.INTERNAL_ERROR`. Tool-level failures
            (permission denied, budget exceeded, unknown/non-allowlisted
            tool) are never raised as JSON-RPC errors — they surface inside
            a successful ``tools/call`` result as ``isError: true``.
        """
        handler = self._methods.get(request.method)
        if handler is None:
            return JsonRpcResponse.failure(request.id, METHOD_NOT_FOUND, f"Method not found: {request.method}")
        try:
            result = handler(request)
        except McpInvalidParamsError as exc:
            return JsonRpcResponse.failure(request.id, INVALID_PARAMS, str(exc))
        except Exception:  # noqa: BLE001 - guard against any unexpected dispatcher bug
            logger.exception("Unhandled error dispatching MCP method %r", request.method)
            return JsonRpcResponse.failure(request.id, INTERNAL_ERROR, "Internal error")
        return JsonRpcResponse.success(request.id, result)

    def _handle_initialize(self, request: JsonRpcRequest) -> dict[str, Any]:
        """Handle the ``initialize`` MCP method.

        Args:
            request: The JSON-RPC request (params are ignored).

        Returns:
            The MCP ``initialize`` result: protocol version, server info, and
            declared capabilities.
        """
        del request
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {"tools": {}},
        }

    def _handle_tools_list(self, request: JsonRpcRequest) -> dict[str, Any]:
        """Handle the ``tools/list`` MCP method.

        Only allowlisted skills (see :attr:`exposed_skills`) are resolved
        and rendered; skills that fail to resolve (e.g. deregistered since
        being allowlisted) are silently omitted rather than surfaced as an
        error, since ``tools/list`` describes what is currently callable.

        Args:
            request: The JSON-RPC request (params are ignored).

        Returns:
            A mapping with a ``tools`` list of MCP tool descriptors.
        """
        del request
        tools: list[dict[str, Any]] = []
        for skill_id in sorted(self._exposed):
            try:
                ref = self._registry.resolve(skill_id)
            except KeyError:
                continue
            tools.append(_tool_descriptor(ref.manifest))
        return {"tools": tools}

    def _handle_tools_call(self, request: JsonRpcRequest) -> dict[str, Any]:
        """Handle the ``tools/call`` MCP method.

        Args:
            request: The JSON-RPC request. ``params`` must be an object with
                a string ``name`` and an optional object ``arguments``.

        Returns:
            A ``content``/``isError`` result. Unknown or non-allowlisted
            tool names, sandbox permission denials (raised directly by a
            skill's guarded imports via
            :class:`~backend.plugins.permissions.PermissionDenied`),
            least-privilege invocation denials, and budget-exceeded failures
            all surface as ``isError: true`` results rather than exceptions
            or JSON-RPC errors, matching MCP's convention that tool
            execution failures are not protocol failures.

        Raises:
            McpInvalidParamsError: If ``params`` does not match the expected
                ``tools/call`` shape.
        """
        params = request.params if request.params is not None else {}
        if not isinstance(params, dict):
            raise McpInvalidParamsError("tools/call params must be an object")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise McpInvalidParamsError("tools/call params.name must be a non-empty string")
        arguments: Any = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise McpInvalidParamsError("tools/call params.arguments must be an object")

        if name not in self._exposed:
            return _text_result(f"Tool not found: {name}", is_error=True)

        try:
            output = self._broker.invoke(name, **arguments)
        except SkillInvocationDenied as exc:
            return _text_result(str(exc), is_error=True)
        except SkillBudgetExceeded as exc:
            return _text_result(str(exc), is_error=True)
        except PermissionDenied as exc:
            return _text_result(str(exc), is_error=True)
        return _text_result(_stringify(output), is_error=False)


__all__ = ["McpInvalidParamsError", "McpServer", "PROTOCOL_VERSION", "SERVER_NAME", "SERVER_VERSION"]
