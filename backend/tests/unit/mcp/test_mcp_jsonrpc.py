"""Tests for the JSON-RPC 2.0 envelope and framing helpers (E9-S4-T1)."""

from __future__ import annotations

import json

import pytest

from backend.mcp.jsonrpc import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcInvalidRequestError,
    JsonRpcParseError,
    JsonRpcRequest,
    JsonRpcResponse,
    parse_request,
    read_line,
    write_line,
)


def test_parse_request_from_dict() -> None:
    request = parse_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert request.method == "initialize"
    assert request.id == 1
    assert request.params == {}
    assert not request.is_notification


def test_parse_request_notification_has_no_id() -> None:
    request = parse_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert request.id is None
    assert request.is_notification


def test_parse_request_rejects_malformed_json() -> None:
    with pytest.raises(JsonRpcParseError):
        parse_request("{not-json")


@pytest.mark.parametrize(
    "raw",
    [
        {"method": "initialize"},  # missing jsonrpc marker
        {"jsonrpc": "1.0", "method": "initialize"},  # wrong version
        {"jsonrpc": "2.0"},  # missing method
        {"jsonrpc": "2.0", "method": ""},  # empty method
        {"jsonrpc": "2.0", "method": "x", "params": "not-an-object-or-array"},
        {"jsonrpc": "2.0", "method": "x", "id": 1.5},
        "[]",  # valid JSON, but not an object
    ],
)
def test_parse_request_rejects_invalid_envelopes(raw: object) -> None:
    with pytest.raises(JsonRpcInvalidRequestError):
        parse_request(raw)  # type: ignore[arg-type]


def test_read_line_rejects_blank_line() -> None:
    with pytest.raises(JsonRpcParseError):
        read_line("   \n")


def test_read_line_parses_valid_request() -> None:
    request = read_line('{"jsonrpc": "2.0", "id": "abc", "method": "tools/list"}\n')
    assert request.method == "tools/list"
    assert request.id == "abc"


def test_write_line_success_response_roundtrips() -> None:
    response = JsonRpcResponse.success(1, {"tools": []})
    line = write_line(response)
    decoded = json.loads(line)
    assert decoded == {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}


def test_write_line_failure_response_includes_error_object() -> None:
    response = JsonRpcResponse.failure(None, METHOD_NOT_FOUND, "Method not found: bogus")
    decoded = json.loads(write_line(response))
    assert decoded["error"]["code"] == METHOD_NOT_FOUND
    assert decoded["error"]["message"] == "Method not found: bogus"
    assert "result" not in decoded


def test_error_codes_match_json_rpc_spec() -> None:
    assert PARSE_ERROR == -32700
    assert INVALID_REQUEST == -32600
    assert METHOD_NOT_FOUND == -32601
    assert INVALID_PARAMS == -32602
    assert INTERNAL_ERROR == -32603


def test_request_from_dict_defaults() -> None:
    request = JsonRpcRequest.from_dict({"jsonrpc": "2.0", "method": "ping", "id": None})
    assert request.method == "ping"
    assert request.id is None
    assert request.params is None
