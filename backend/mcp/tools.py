"""Adapter registering external MCP tools into the Agent Runtime (E9-S4-T2/T3).

Declares MCP servers as explicit, least-privilege tool providers: each
server carries its own transport, connection details, and an **allowlist**
of tool names it is permitted to expose (:class:`McpServerConfig`). Only
allowlisted tools that the server actually advertises via ``tools/list``
are registered; a server with an empty allowlist contributes no tools at
all (E9-S4-T3, deny-by-default).

Registered tools are plain callables keyed by ``mcp:<server>:<tool>``,
suitable for the ``tools`` mapping accepted by
:class:`backend.agents.runtime.AgentRuntime` and
:class:`backend.agents.tools.AgentToolBroker`. Because invocation still
flows through :meth:`backend.agents.runtime.AgentRuntimeContext.call_tool`,
every MCP call automatically consumes the run's tool-call budget and is
still gated by the agent manifest's own ``permissions.tools`` allowlist —
this module only controls which MCP tools exist to be granted at all.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
from typing import Any, Literal

from backend.mcp.client import McpClient, McpError, McpHttpClient, McpStdioClient

logger = logging.getLogger(__name__)

_TRANSPORTS = ("stdio", "http")


@dataclass(frozen=True)
class McpServerConfig:
    """Declarative configuration for one external MCP server.

    Attributes:
        name: Short, unique identifier for the server; used as the
            namespace segment of every tool id it registers
            (``mcp:<name>:<tool>``).
        transport: Wire transport used to reach the server.
        command: Subprocess argv launching the server; required, and only
            meaningful, for ``transport="stdio"``.
        url: HTTP endpoint of the server; required, and only meaningful,
            for ``transport="http"``.
        allowlist: Tool names this server is permitted to expose. An empty
            allowlist grants **no** tools (least privilege, E9-S4-T3):
            discovery still runs, but nothing is registered.
        timeout_s: Per-call timeout applied to every tool invocation on
            this server.
    """

    name: str
    transport: Literal["stdio", "http"]
    command: tuple[str, ...] = ()
    url: str = ""
    allowlist: tuple[str, ...] = ()
    timeout_s: float = 10.0

    def __post_init__(self) -> None:
        """Validate that the config carries what its transport requires.

        Raises:
            ValueError: If ``transport`` is unsupported, or the transport's
                required connection detail (``command``/``url``) is missing.
        """
        if self.transport not in _TRANSPORTS:
            raise ValueError(f"MCP server {self.name!r}: unsupported transport {self.transport!r}")
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"MCP server {self.name!r}: stdio transport requires a non-empty command")
        if self.transport == "http" and not self.url:
            raise ValueError(f"MCP server {self.name!r}: http transport requires a url")

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> McpServerConfig:
        """Build a config from a plain mapping (e.g. parsed JSON/YAML).

        Args:
            raw: Mapping with ``name``, ``transport``, and the fields
                relevant to that transport (``command`` or ``url``), plus
                optional ``allowlist`` and ``timeoutS``.

        Returns:
            The parsed, validated server config.

        Raises:
            ValueError: If required fields are missing or malformed.
        """
        name = raw.get("name")
        transport = raw.get("transport")
        if not isinstance(name, str) or not name:
            raise ValueError("MCP server config requires a non-empty 'name'")
        if transport not in _TRANSPORTS:
            raise ValueError(f"MCP server {name!r}: 'transport' must be one of {_TRANSPORTS}")
        command_raw = raw.get("command", ())
        command = tuple(command_raw) if isinstance(command_raw, (list, tuple)) else ()
        allowlist_raw = raw.get("allowlist", ())
        allowlist = tuple(allowlist_raw) if isinstance(allowlist_raw, (list, tuple)) else ()
        return cls(
            name=name,
            transport=transport,
            command=command,
            url=str(raw.get("url", "")),
            allowlist=allowlist,
            timeout_s=float(raw.get("timeoutS", 10.0)),
        )


class McpToolProvider:
    """Discovers tools from configured MCP servers and exposes them as agent tools.

    Usage::

        provider = McpToolProvider([server_config, ...])
        tools = provider.connect()
        runtime = AgentRuntime(tools=tools)
        ...
        provider.close()

    Or as a context manager::

        with McpToolProvider([server_config, ...]) as provider:
            runtime = AgentRuntime(tools=provider.tools)
            ...
    """

    def __init__(self, servers: Sequence[McpServerConfig]) -> None:
        """Store the server configs without connecting to any of them yet.

        Args:
            servers: MCP server configs to discover tools from on :meth:`connect`.
        """
        self._servers = list(servers)
        self._clients: dict[str, McpClient] = {}
        self._tools: dict[str, Callable[..., Any]] = {}

    def __enter__(self) -> McpToolProvider:
        """Connect to every configured server and return this provider."""
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close every connected server client on exit from a ``with`` block."""
        self.close()

    def connect(self) -> dict[str, Callable[..., Any]]:
        """Connect to every configured server and register its allowlisted tools.

        For each server: skip it entirely if its allowlist is empty (T3
        deny-by-default); otherwise connect, ``initialize``, discover tools
        via ``tools/list``, and register a callable for every allowlisted
        name the server actually advertises. Discovery failures and
        unmatched allowlist entries are logged and skipped rather than
        raised, so one misbehaving server cannot prevent the others from
        being registered.

        Returns:
            The full set of newly registered tool callables, keyed by
            ``mcp:<server>:<tool>``.
        """
        for server in self._servers:
            if not server.allowlist:
                logger.warning("MCP server %r has an empty allowlist; no tools will be registered", server.name)
                continue
            self._connect_one(server)
        return dict(self._tools)

    def _connect_one(self, server: McpServerConfig) -> None:
        """Connect to a single server and register its allowlisted tools.

        Args:
            server: Server config to connect to; its allowlist is assumed non-empty.
        """
        client = _build_client(server)
        try:
            client.initialize()
            discovered = {
                tool["name"] for tool in client.list_tools() if isinstance(tool.get("name"), str)
            }
        except McpError:
            logger.exception("Failed to discover tools from MCP server %r", server.name)
            client.close()
            return
        self._clients[server.name] = client
        for tool_name in server.allowlist:
            if tool_name not in discovered:
                logger.warning(
                    "Allowlisted tool %r not offered by MCP server %r; skipping", tool_name, server.name
                )
                continue
            tool_id = f"mcp:{server.name}:{tool_name}"
            self._tools[tool_id] = _make_invoker(client, tool_name, server.timeout_s)

    @property
    def tools(self) -> dict[str, Callable[..., Any]]:
        """Return a copy of the currently registered tool callables."""
        return dict(self._tools)

    def close(self) -> None:
        """Close every connected server client and forget registered tools."""
        for client in self._clients.values():
            client.close()
        self._clients.clear()
        self._tools.clear()


def _make_invoker(client: McpClient, tool_name: str, timeout_s: float) -> Callable[..., Any]:
    """Build a tool callable that forwards keyword arguments to ``client.call_tool``.

    Args:
        client: Connected MCP client to invoke the tool on.
        tool_name: Name of the tool as advertised by the server.
        timeout_s: Per-call timeout to apply.

    Returns:
        A callable matching the ``Callable[..., Any]`` signature expected
        by :class:`backend.agents.tools.AgentToolBroker`'s ``tools`` mapping.
    """

    def _invoke(**kwargs: Any) -> Any:
        """Invoke the bound MCP tool with keyword arguments as its ``arguments``."""
        return client.call_tool(tool_name, kwargs, timeout_s=timeout_s)

    return _invoke


def _build_client(server: McpServerConfig) -> McpClient:
    """Build the transport-appropriate client for a server config.

    Args:
        server: Server config carrying transport and connection details.

    Returns:
        A connected-but-not-yet-initialized :class:`McpClient`.
    """
    if server.transport == "stdio":
        return McpStdioClient(server.command, timeout_s=server.timeout_s)
    return McpHttpClient(server.url, timeout_s=server.timeout_s)


__all__ = ["McpServerConfig", "McpToolProvider"]
