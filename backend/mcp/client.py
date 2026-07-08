"""MCP client transports: consume external MCP servers as tool providers (E9-S4-T2).

Implements a minimal Model Context Protocol client speaking JSON-RPC 2.0
without depending on the ``mcp`` pip package. Two transports are provided:

- :class:`McpStdioClient` spawns a server subprocess and exchanges one JSON
  object per line over its stdin/stdout.
- :class:`McpHttpClient` POSTs JSON-RPC requests to an HTTP endpoint, using
  ``httpx`` as an optional, lazily imported dependency (mirroring the
  ``redis`` optional-import pattern in :mod:`backend.coordination.redis`).

Both transports expose the same surface: :meth:`initialize`, ``list_tools``,
and ``call_tool``, and raise :class:`McpError` for any protocol, transport,
or timeout failure instead of hanging or leaking a lower-level exception.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
import queue
import subprocess
import threading
from typing import Any, Protocol


class McpError(RuntimeError):
    """Raised for any MCP protocol, transport, or timeout failure."""


class McpClient(Protocol):
    """Structural interface shared by every MCP client transport."""

    def initialize(self, **params: Any) -> Any:
        """Send the MCP ``initialize`` handshake request."""
        ...

    def list_tools(self) -> list[dict[str, Any]]:
        """List the tools offered by the server."""
        ...

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, *, timeout_s: float | None = None
    ) -> Any:
        """Invoke a named tool on the server and return its result."""
        ...

    def close(self) -> None:
        """Release any resources (subprocess, connection) held by the client."""
        ...


def _extract_result(message: Any, expected_id: int) -> Any:
    """Validate a decoded JSON-RPC response object and return its result.

    Args:
        message: Decoded JSON value received from the server.
        expected_id: The request id this response must match.

    Returns:
        The value of the response's ``result`` field.

    Raises:
        McpError: If the message is not a well-formed JSON-RPC 2.0 response,
            does not match ``expected_id``, or carries an ``error`` member.
    """
    if not isinstance(message, dict):
        raise McpError("JSON-RPC response must be a JSON object")
    if message.get("id") != expected_id:
        raise McpError(f"JSON-RPC response id mismatch: expected {expected_id}, got {message.get('id')!r}")
    error = message.get("error")
    if error is not None:
        if isinstance(error, dict):
            raise McpError(f"MCP server error {error.get('code')}: {error.get('message')}")
        raise McpError(f"MCP server error: {error!r}")
    return message.get("result")


class McpStdioClient:
    """MCP client speaking line-delimited JSON-RPC 2.0 over a subprocess's stdio.

    Spawns ``command`` as a child process and exchanges one JSON object per
    line on its stdin/stdout. Each in-flight request is tracked by its
    ``id`` on a dedicated reader thread, so a per-call timeout can be
    enforced without blocking the caller on the pipe, and a slow or
    malformed response cannot corrupt a later call. Use as a context
    manager, or call :meth:`close` explicitly, to terminate the child
    process.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_s: float = 10.0,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize the client without starting the subprocess yet.

        Args:
            command: Argv used to spawn the MCP server subprocess.
            timeout_s: Default per-call timeout, in seconds.
            cwd: Working directory for the subprocess, if any.
            env: Environment variables for the subprocess; inherits the
                current process's environment when omitted.
        """
        self._command = list(command)
        self._timeout_s = timeout_s
        self._cwd = cwd
        self._env = env
        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._pending: dict[int, queue.Queue[tuple[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 0
        self._id_lock = threading.Lock()

    def __enter__(self) -> McpStdioClient:
        """Start the subprocess and return this client for ``with`` usage."""
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Terminate the subprocess on exit from a ``with`` block."""
        self.close()

    def start(self) -> None:
        """Spawn the subprocess and start the background stdout reader.

        A no-op if the subprocess is already running.

        Raises:
            McpError: If the subprocess cannot be started.
        """
        if self._proc is not None:
            return
        try:
            self._proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                cwd=self._cwd,
                env=self._env,
            )
        except OSError as exc:
            raise McpError(f"failed to start MCP server {self._command!r}: {exc}") from exc
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _read_loop(self) -> None:
        """Continuously read stdout lines and dispatch them to pending callers."""
        proc = self._proc
        if proc is None or proc.stdout is None:  # pragma: no cover - defensive
            return
        try:
            for line in proc.stdout:
                self._dispatch_line(line)
        except (ValueError, OSError):  # pragma: no cover - pipe torn down during close()
            pass
        self._dispatch_eof()

    def _dispatch_line(self, raw: str) -> None:
        """Parse one stdout line and route it to the matching pending request.

        A malformed line is broadcast as an error to every in-flight
        request rather than silently dropped, so a caller waiting on a
        response never hangs past its timeout because of bad server output.

        Args:
            raw: One raw line read from the subprocess's stdout.
        """
        raw = raw.strip()
        if not raw:
            return
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._broadcast(("error", f"malformed JSON-RPC message from MCP server: {exc}"))
            return
        if not isinstance(message, dict) or "id" not in message:
            return
        with self._pending_lock:
            target = self._pending.get(message["id"])
        if target is not None:
            target.put(("message", message))

    def _broadcast(self, item: tuple[str, Any]) -> None:
        """Deliver ``item`` to every currently in-flight request's inbox."""
        with self._pending_lock:
            targets = list(self._pending.values())
        for target in targets:
            target.put(item)

    def _dispatch_eof(self) -> None:
        """Notify every in-flight request that the server closed its output."""
        self._broadcast(("eof", None))

    def _allocate_id(self) -> int:
        """Return the next unique JSON-RPC request id."""
        with self._id_lock:
            self._next_id += 1
            return self._next_id

    def _request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout_s: float | None = None
    ) -> Any:
        """Send one JSON-RPC request and block for its matching response.

        Args:
            method: JSON-RPC method name.
            params: JSON-RPC params object.
            timeout_s: Per-call timeout override, in seconds.

        Returns:
            The response's ``result`` value.

        Raises:
            McpError: On timeout, a transport failure, or a malformed/errored response.
        """
        self.start()
        proc = self._proc
        assert proc is not None and proc.stdin is not None  # start() guarantees this
        req_id = self._allocate_id()
        inbox: queue.Queue[tuple[str, Any]] = queue.Queue()
        with self._pending_lock:
            self._pending[req_id] = inbox
        try:
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
            line = json.dumps(payload) + "\n"
            with self._write_lock:
                try:
                    proc.stdin.write(line)
                    proc.stdin.flush()
                except (BrokenPipeError, ValueError, OSError) as exc:
                    raise McpError(f"failed to write to MCP server: {exc}") from exc
            effective_timeout = timeout_s if timeout_s is not None else self._timeout_s
            try:
                kind, value = inbox.get(timeout=effective_timeout)
            except queue.Empty as exc:
                raise McpError(f"MCP server did not respond within {effective_timeout}s") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(req_id, None)
        if kind == "error":
            raise McpError(str(value))
        if kind == "eof":
            raise McpError("MCP server closed its output stream unexpectedly")
        return _extract_result(value, req_id)

    def initialize(self, **params: Any) -> Any:
        """Send the MCP ``initialize`` handshake request.

        Args:
            **params: Optional initialize parameters forwarded to the server.

        Returns:
            The server's initialize result payload.

        Raises:
            McpError: On timeout, transport failure, or a malformed/errored response.
        """
        return self._request("initialize", params)

    def list_tools(self) -> list[dict[str, Any]]:
        """List tools offered by the server via ``tools/list``.

        Returns:
            The server's advertised tool descriptors (each with at least a
            ``name`` key), or an empty list if the server returned none.

        Raises:
            McpError: On timeout, transport failure, or a malformed/errored response.
        """
        result = self._request("tools/list")
        if isinstance(result, dict) and isinstance(result.get("tools"), list):
            return [tool for tool in result["tools"] if isinstance(tool, dict)]
        return []

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, *, timeout_s: float | None = None
    ) -> Any:
        """Invoke a named tool on the server via ``tools/call``.

        Args:
            name: Tool name to invoke.
            arguments: Keyword arguments passed to the tool.
            timeout_s: Per-call timeout override; defaults to the client's configured timeout.

        Returns:
            The tool's result payload (MCP content).

        Raises:
            McpError: On timeout, transport failure, or a malformed/errored response.
        """
        return self._request("tools/call", {"name": name, "arguments": arguments or {}}, timeout_s=timeout_s)

    def close(self) -> None:
        """Terminate the subprocess and stop the reader thread.

        Safe to call more than once; any request still waiting for a
        response is unblocked with an ``eof`` result.
        """
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:  # noqa: BLE001 - best-effort shutdown
            pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001 - best-effort shutdown
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 - best-effort shutdown
                pass
        self._dispatch_eof()


class McpHttpClient:
    """MCP client speaking JSON-RPC 2.0 over HTTP POST.

    Uses ``httpx`` as an optional dependency, imported lazily on first use so
    that importing this module never requires ``httpx`` to be installed
    (mirroring the ``redis`` optional-import pattern used by
    :mod:`backend.events.bus`).
    """

    def __init__(self, url: str, *, timeout_s: float = 10.0, headers: dict[str, str] | None = None) -> None:
        """Initialize the client without opening a connection yet.

        Args:
            url: HTTP endpoint the server's JSON-RPC handler listens on.
            timeout_s: Default per-call timeout, in seconds.
            headers: Extra HTTP headers sent with every request (e.g. auth).
        """
        self._url = url
        self._timeout_s = timeout_s
        self._headers = dict(headers or {})
        self._client: Any | None = None
        self._next_id = 0
        self._id_lock = threading.Lock()

    def __enter__(self) -> McpHttpClient:
        """Return this client for ``with`` usage; no connection setup required."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the underlying HTTP connection on exit from a ``with`` block."""
        self.close()

    def _http_client(self) -> Any:
        """Build (once) and return the underlying ``httpx.Client``.

        Raises:
            RuntimeError: If the ``httpx`` package is not installed.
        """
        if self._client is None:
            try:
                import httpx  # noqa: PLC0415 - intentionally optional/lazy
            except ImportError as exc:  # pragma: no cover - environment guard
                raise RuntimeError("httpx package is not installed; required for McpHttpClient") from exc
            self._client = httpx.Client(headers=self._headers)
        return self._client

    def _allocate_id(self) -> int:
        """Return the next unique JSON-RPC request id."""
        with self._id_lock:
            self._next_id += 1
            return self._next_id

    def _request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout_s: float | None = None
    ) -> Any:
        """POST one JSON-RPC request and return its validated result.

        Args:
            method: JSON-RPC method name.
            params: JSON-RPC params object.
            timeout_s: Per-call timeout override, in seconds.

        Returns:
            The response's ``result`` value.

        Raises:
            McpError: On a transport failure, HTTP error status, or a
                malformed/errored JSON-RPC response.
        """
        req_id = self._allocate_id()
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        client = self._http_client()
        effective_timeout = timeout_s if timeout_s is not None else self._timeout_s
        try:
            response = client.post(self._url, json=payload, timeout=effective_timeout)
        except Exception as exc:  # noqa: BLE001 - httpx raises its own hierarchy; normalize to McpError
            raise McpError(f"HTTP request to MCP server failed: {exc}") from exc
        if response.status_code >= 400:
            raise McpError(f"MCP server returned HTTP {response.status_code}")
        try:
            message = response.json()
        except ValueError as exc:
            raise McpError(f"malformed JSON-RPC response: {exc}") from exc
        return _extract_result(message, req_id)

    def initialize(self, **params: Any) -> Any:
        """Send the MCP ``initialize`` handshake request.

        Args:
            **params: Optional initialize parameters forwarded to the server.

        Returns:
            The server's initialize result payload.

        Raises:
            McpError: On a transport failure, HTTP error status, or a
                malformed/errored JSON-RPC response.
        """
        return self._request("initialize", params)

    def list_tools(self) -> list[dict[str, Any]]:
        """List tools offered by the server via ``tools/list``.

        Returns:
            The server's advertised tool descriptors, or an empty list if
            the server returned none.

        Raises:
            McpError: On a transport failure, HTTP error status, or a
                malformed/errored JSON-RPC response.
        """
        result = self._request("tools/list")
        if isinstance(result, dict) and isinstance(result.get("tools"), list):
            return [tool for tool in result["tools"] if isinstance(tool, dict)]
        return []

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, *, timeout_s: float | None = None
    ) -> Any:
        """Invoke a named tool on the server via ``tools/call``.

        Args:
            name: Tool name to invoke.
            arguments: Keyword arguments passed to the tool.
            timeout_s: Per-call timeout override; defaults to the client's configured timeout.

        Returns:
            The tool's result payload (MCP content).

        Raises:
            McpError: On a transport failure, HTTP error status, or a
                malformed/errored JSON-RPC response.
        """
        return self._request("tools/call", {"name": name, "arguments": arguments or {}}, timeout_s=timeout_s)

    def close(self) -> None:
        """Close the underlying HTTP connection, if one was opened.

        Safe to call more than once.
        """
        if self._client is not None:
            self._client.close()
            self._client = None


__all__ = ["McpClient", "McpError", "McpHttpClient", "McpStdioClient"]
