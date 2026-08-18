"""Tests for `autodev` CLI packaging & install behavior (E14-S7).

Covers: argument parsing for the new `permissions` subcommand, the
`permissions list`/`revoke` handlers (mocked HTTP, matching the shell's
API-only style), and the no-args path starting the web server and opening
the browser — with `uvicorn`/`httpx`/`webbrowser` all mocked so this test
never binds a real socket or opens a real browser.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from backend.cli import build_parser, main


def test_permissions_subcommands_parse() -> None:
    parser = build_parser()

    list_args = parser.parse_args(["permissions", "list"])
    assert list_args.command == "permissions"
    assert list_args.permissions_command == "list"

    revoke_args = parser.parse_args(["permissions", "revoke", "perm-1", "--base-url", "http://x"])
    assert revoke_args.permissions_command == "revoke"
    assert revoke_args.permission_id == "perm-1"
    assert revoke_args.base_url == "http://x"


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttpxClient:
    """Records calls and returns scripted responses; mirrors httpx.Client's context-manager API."""

    calls: list[tuple[str, str]] = []
    get_response: dict[str, Any] = {"permissions": []}

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> "_FakeHttpxClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        _FakeHttpxClient.calls.append(("GET", url))
        return _FakeResponse(_FakeHttpxClient.get_response)

    def delete(self, url: str, **kwargs: object) -> _FakeResponse:
        _FakeHttpxClient.calls.append(("DELETE", url))
        return _FakeResponse({})


@pytest.fixture(autouse=True)
def _reset_fake_httpx_client() -> None:
    _FakeHttpxClient.calls = []
    _FakeHttpxClient.get_response = {"permissions": []}


def test_permissions_list_prints_each_grant(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import httpx

    monkeypatch.setattr(httpx, "Client", _FakeHttpxClient)
    _FakeHttpxClient.get_response = {
        "permissions": [{"permissionId": "perm-1", "category": "shell", "pattern": "pytest"}]
    }

    exit_code = main(["permissions", "list"])

    assert exit_code == 0
    assert _FakeHttpxClient.calls == [("GET", "/v2/execution/policy/dynamic")]
    assert "perm-1" in capsys.readouterr().out


def test_permissions_revoke_calls_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "Client", _FakeHttpxClient)

    exit_code = main(["permissions", "revoke", "perm-1"])

    assert exit_code == 0
    assert _FakeHttpxClient.calls == [("DELETE", "/v2/execution/policy/dynamic/perm-1")]


class _FakeServer:
    """Stands in for uvicorn.Server: blocks briefly (bounded) instead of forever."""

    instances: list["_FakeServer"] = []

    def __init__(self, config: object) -> None:
        self.config = config
        self.should_exit = False
        _FakeServer.instances.append(self)

    def run(self) -> None:
        deadline = time.monotonic() + 1.0
        while not self.should_exit and time.monotonic() < deadline:
            time.sleep(0.01)


@pytest.fixture(autouse=True)
def _reset_fake_server() -> None:
    _FakeServer.instances = []


class _HealthyResponse:
    status_code = 200


class _HealthCheckClient:
    """Stands in for httpx.Client during the /health poll: always reports healthy."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> "_HealthCheckClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> _HealthyResponse:
        return _HealthyResponse()


def test_no_args_starts_the_server_and_opens_the_browser_at_the_root_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import httpx
    import uvicorn

    monkeypatch.setattr(uvicorn, "Server", _FakeServer)
    monkeypatch.setattr(httpx, "Client", _HealthCheckClient)

    opened: list[str] = []

    def fake_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr("webbrowser.open", fake_open)
    monkeypatch.setenv("AUTODEV_HOST", "127.0.0.1")
    monkeypatch.setenv("AUTODEV_PORT", "8123")

    # Let the fake server's bounded run() finish naturally (<=1s) instead of
    # blocking main()'s own `while thread.is_alive(): thread.join()` loop.
    exit_code = main([])

    assert exit_code == 0
    assert opened == ["http://127.0.0.1:8123/"]
    assert "AutoDev is running at http://127.0.0.1:8123/" in capsys.readouterr().out
