"""JSON-RPC 2.0 envelope and line-delimited framing for MCP (E9-S4-T1).

Deliberately stdlib-only (no ``mcp`` or ``jsonrpclib`` dependency), matching
this repository's no-heavy-deps stance: a minimal, spec-shaped JSON-RPC 2.0
layer is enough to carry the small MCP method set (``initialize``,
``tools/list``, ``tools/call``) over either stdio or HTTP transports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Union

JSONRPC_VERSION = "2.0"

#: Standard JSON-RPC 2.0 error codes (https://www.jsonrpc.org/specification#error_object).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

RequestId = Union[str, int, None]


class JsonRpcParseError(ValueError):
    """Raised when raw input is not well-formed JSON.

    Callers should map this to a JSON-RPC error response with code
    :data:`PARSE_ERROR`.
    """


class JsonRpcInvalidRequestError(ValueError):
    """Raised when parsed JSON is not a valid JSON-RPC 2.0 request object.

    Callers should map this to a JSON-RPC error response with code
    :data:`INVALID_REQUEST`.
    """


@dataclass(frozen=True)
class JsonRpcError:
    """A JSON-RPC 2.0 error object.

    Attributes:
        code: A standard or application-defined error code.
        message: Short, human-readable error description.
        data: Optional additional error information.
    """

    code: int
    message: str
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Render this error as a JSON-serializable mapping.

        Returns:
            The error object, including ``data`` only when set.
        """
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            payload["data"] = self.data
        return payload


@dataclass(frozen=True)
class JsonRpcRequest:
    """A parsed JSON-RPC 2.0 request (or notification).

    Attributes:
        method: The name of the method to invoke.
        id: Request identifier. ``None`` for notifications (no reply expected).
        params: Positional (list) or named (dict) parameters, if any.
        jsonrpc: Protocol version marker; always ``"2.0"``.
    """

    method: str
    id: RequestId = None
    params: dict[str, Any] | list[Any] | None = None
    jsonrpc: str = JSONRPC_VERSION

    @property
    def is_notification(self) -> bool:
        """Whether this request expects no response (has no ``id``)."""
        return self.id is None

    @classmethod
    def from_dict(cls, raw: Any) -> "JsonRpcRequest":
        """Parse an already-decoded JSON object into a :class:`JsonRpcRequest`.

        Args:
            raw: The decoded JSON value, expected to be a JSON-RPC 2.0 request object.

        Returns:
            The parsed request.

        Raises:
            JsonRpcInvalidRequestError: If ``raw`` is not a valid JSON-RPC 2.0
                request object (wrong ``jsonrpc`` marker, missing/non-string
                ``method``, or malformed ``params``).
        """
        if not isinstance(raw, dict):
            raise JsonRpcInvalidRequestError("Request must be a JSON object")
        if raw.get("jsonrpc") != JSONRPC_VERSION:
            raise JsonRpcInvalidRequestError('Request must set "jsonrpc": "2.0"')
        method = raw.get("method")
        if not isinstance(method, str) or not method:
            raise JsonRpcInvalidRequestError('Request must have a non-empty string "method"')
        params = raw.get("params")
        if params is not None and not isinstance(params, (dict, list)):
            raise JsonRpcInvalidRequestError('"params" must be an object or array when present')
        request_id = raw.get("id")
        if request_id is not None and not isinstance(request_id, (str, int)):
            raise JsonRpcInvalidRequestError('"id" must be a string, number, or null when present')
        return cls(method=method, id=request_id, params=params)


@dataclass(frozen=True)
class JsonRpcResponse:
    """A JSON-RPC 2.0 response: either a success (``result``) or a failure (``error``).

    Attributes:
        id: Echoes the originating request's ``id``.
        result: The method's return value, present only on success.
        error: The error object, present only on failure.
        jsonrpc: Protocol version marker; always ``"2.0"``.
    """

    id: RequestId
    result: Any = None
    error: JsonRpcError | None = None
    jsonrpc: str = JSONRPC_VERSION

    @classmethod
    def success(cls, request_id: RequestId, result: Any) -> "JsonRpcResponse":
        """Build a successful response.

        Args:
            request_id: The originating request's ``id``.
            result: The method's return value.

        Returns:
            The success response.
        """
        return cls(id=request_id, result=result)

    @classmethod
    def failure(cls, request_id: RequestId, code: int, message: str, data: Any = None) -> "JsonRpcResponse":
        """Build a failure response.

        Args:
            request_id: The originating request's ``id`` (``None`` if the
                request itself could not be parsed).
            code: A standard or application-defined JSON-RPC error code.
            message: Short, human-readable error description.
            data: Optional additional error information.

        Returns:
            The failure response.
        """
        return cls(id=request_id, error=JsonRpcError(code=code, message=message, data=data))

    def to_dict(self) -> dict[str, Any]:
        """Render this response as a JSON-serializable mapping.

        Returns:
            The response object, with exactly one of ``result``/``error`` set.
        """
        payload: dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            payload["error"] = self.error.to_dict()
        else:
            payload["result"] = self.result
        return payload


def parse_request(raw: str | bytes | dict[str, Any]) -> JsonRpcRequest:
    """Parse a raw JSON-RPC request from text/bytes or an already-decoded object.

    Args:
        raw: A JSON document (str/bytes) or an already-decoded mapping.

    Returns:
        The parsed request.

    Raises:
        JsonRpcParseError: If ``raw`` is text/bytes that is not valid JSON.
        JsonRpcInvalidRequestError: If the decoded value is not a valid
            JSON-RPC 2.0 request object.
    """
    if isinstance(raw, (str, bytes)):
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise JsonRpcParseError(str(exc)) from exc
    else:
        decoded = raw
    return JsonRpcRequest.from_dict(decoded)


def read_line(line: str) -> JsonRpcRequest:
    """Parse a single line of line-delimited JSON-RPC input.

    Args:
        line: One line of input, with or without a trailing newline.

    Returns:
        The parsed request.

    Raises:
        JsonRpcParseError: If the line is blank or not valid JSON.
        JsonRpcInvalidRequestError: If the decoded value is not a valid
            JSON-RPC 2.0 request object.
    """
    stripped = line.strip()
    if not stripped:
        raise JsonRpcParseError("Empty line is not a valid JSON-RPC request")
    return parse_request(stripped)


def write_line(response: JsonRpcResponse) -> str:
    """Serialize a response into a single line-delimited JSON line.

    Args:
        response: The response to serialize.

    Returns:
        A single-line JSON document (no trailing newline).
    """
    return json.dumps(response.to_dict())


__all__ = [
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "JSONRPC_VERSION",
    "JsonRpcError",
    "JsonRpcInvalidRequestError",
    "JsonRpcParseError",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "RequestId",
    "parse_request",
    "read_line",
    "write_line",
]
