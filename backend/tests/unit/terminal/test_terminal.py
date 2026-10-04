"""E65: PTY session, manager and WebSocket route."""

from __future__ import annotations

import time
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache
from backend.terminal.manager import TerminalCapError, TerminalManager
from backend.terminal.session import TerminalSession, build_session_env


def _wait_for(session: TerminalSession, needle: bytes, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if needle in session.scrollback():
            return
        time.sleep(0.05)
    raise AssertionError(f"{needle!r} not seen in {session.scrollback()!r}")


def test_env_is_allowlisted() -> None:
    env = build_session_env({"PATH": "/bin", "OPENAI_API_KEY": "secret", "HOME": "/h"})
    assert "OPENAI_API_KEY" not in env and env["TERM"] == "xterm-256color"


def test_echo_cwd_interrupt_and_reap(tmp_path: Path) -> None:
    session = TerminalSession(tmp_path, shell="/bin/sh")
    try:
        session.write(b"echo hi-$((20+22))\n")
        _wait_for(session, b"hi-42")
        session.write(b"pwd\n")
        _wait_for(session, str(tmp_path.resolve()).encode())
        session.write(b"sleep 30\n")
        time.sleep(0.3)
        session.write(b"\x03")
        session.write(b"echo recovered\n")
        _wait_for(session, b"recovered")
        session.resize(100, 30)
    finally:
        session.close()
    assert session.exited.is_set()


def test_manager_key_cap_and_project_isolation(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    manager = TerminalManager(max_per_tenant=2)
    try:
        s1, created = manager.attach("t", a, "term")
        s2, created2 = manager.attach("t", a, "term")
        s3, _ = manager.attach("t", b, "term")
        assert created and not created2 and s1 is s2 and s3 is not s1
        with pytest.raises(TerminalCapError):
            manager.attach("t", a, "other")
    finally:
        manager.close_all()


def test_idle_session_is_reaped(tmp_path: Path) -> None:
    manager = TerminalManager(idle_ttl=0.0)
    session, _ = manager.attach("t", tmp_path, "x")
    time.sleep(0.05)
    manager.sweep()
    assert session.exited.is_set()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'term.db'}")
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.setenv("AUTODEV_API_TOKEN", "")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    from backend.api.main import app

    with TestClient(app) as c:
        yield c
    reset_settings_cache()
    reset_store_cache()
    reset_runtime_config_cache()


def test_ws_closed_4403_when_disabled(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/v2/terminal/t1"):
            pass
    assert exc.value.code == 4403
    assert client.get("/v2/terminal/status").json() == {"enabled": False}


def test_ws_info_and_io_when_enabled(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_TERMINAL", "true")
    reset_settings_cache()
    assert client.get("/v2/terminal/status").json() == {"enabled": True}
    with client.websocket_connect("/v2/terminal/t1") as ws:
        info = ws.receive_json()
        assert info["type"] == "info" and info["projectRoot"] == str(tmp_path.resolve())
        ws.send_json({"type": "input", "data": "echo ws-$((1+2))\n"})
        seen = ""
        deadline = time.monotonic() + 5
        while "ws-3" not in seen and time.monotonic() < deadline:
            frame = ws.receive_json()
            if frame["type"] == "output":
                seen += frame["data"]
        assert "ws-3" in seen
    from backend.terminal.manager import get_terminal_manager

    get_terminal_manager().close_all()


def test_ws_rejects_token_query(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setenv("AUTODEV_ENABLE_TERMINAL", "true")
    reset_settings_cache()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/v2/terminal/t1?token=abc"):
            pass
    assert exc.value.code == 4401


def test_prod_profile_refuses_without_override() -> None:
    from backend.config.settings import Settings
    from backend.terminal.manager import terminal_enabled

    assert not terminal_enabled(Settings(autodev_enable_terminal=False))
    assert terminal_enabled(Settings(autodev_enable_terminal=True))
    prod = Settings.model_construct(
        autodev_enable_terminal=True, autodev_terminal_allow_prod=False, autodev_profile="prod"
    )
    assert not terminal_enabled(prod)
    prod.autodev_terminal_allow_prod = True
    assert terminal_enabled(prod)


def test_websocket_routes_are_public_and_self_authorizing(client: TestClient) -> None:
    """The HTTP-only coverage contract skips WebSockets, so pin them here."""
    from starlette.routing import WebSocketRoute

    from backend.api.authorization import is_public_endpoint
    from backend.api.main import app

    def flatten(routes):  # noqa: ANN001, ANN202
        for r in routes:
            if isinstance(r, WebSocketRoute):
                yield r
            elif hasattr(r, "original_router"):
                yield from flatten(r.original_router.routes)
            elif hasattr(r, "routes"):
                yield from flatten(r.routes)

    ws_routes = list(flatten(app.routes))
    assert ws_routes
    for route in ws_routes:
        assert is_public_endpoint(route.endpoint), route.path
        assert "authorize_websocket" in route.endpoint.__code__.co_names, route.path


def test_ws_allow_is_audited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_TERMINAL", "true")
    reset_settings_cache()
    records = []
    from backend.auth import audit

    class _Writer:
        def record(self, record, required=True):  # noqa: ANN001
            records.append(record)

    monkeypatch.setattr("backend.api.authorization.get_audit_writer", lambda: _Writer())
    with client.websocket_connect("/v2/terminal/audit1") as ws:
        ws.receive_json()
    from backend.terminal.manager import get_terminal_manager

    get_terminal_manager().close_all()
    assert [(r.method, r.decision, r.required_scope) for r in records] == [
        ("WEBSOCKET", "allowed", "terminal:use")
    ]
    assert audit is not None
