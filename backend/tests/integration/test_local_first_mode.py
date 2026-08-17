"""Local-first mode evidence for the v2.0-alpha wave gate.

The Alpha gate requires that "local-first mode (SQLite + stub provider) runs
with no external dependencies". Every other Alpha criterion had a named test
behind it; this one only had the indirect argument that the suite happens to
pass offline, which proves nothing about a *deliberate* attempt to reach the
network.

These tests make the claim falsifiable: every outbound socket to a non-loopback
address is blocked for their duration, so a run that silently depends on
PostgreSQL, Redis, an OTLP collector, or a hosted model provider fails here
instead of passing quietly on a developer machine that happens to have them.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.config.settings import get_settings, reset_settings_cache
from backend.events.runtime import (
    reset_event_bus_for_tests,
    reset_event_store_for_tests,
)
from backend.flows.engine import FlowEngine
from backend.flows.handlers import CallableRegistry, build_default_handlers
from backend.persistence.database import reset_store_cache

#: Environment variables that would point the platform at an external service.
#: All are cleared so the defaults -- and only the defaults -- are exercised.
_EXTERNAL_SERVICE_ENV_VARS = (
    "DATABASE_URL",
    "AUTODEV_REDIS_URL",
    "AUTODEV_EVENT_BUS",
    "AUTODEV_EVENT_STORE_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "LLM_PROVIDER",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


class ExternalNetworkAttempt(AssertionError):
    """Raised when code under test opens a socket to a non-loopback address."""


def _is_loopback(address: Any) -> bool:
    """Return whether a socket address is loopback or a local unix path.

    Args:
        address: The address passed to ``socket.socket.connect``.

    Returns:
        ``True`` for loopback IPs and non-tuple (unix socket) addresses.
    """
    if not isinstance(address, tuple) or not address:
        # AF_UNIX paths and similar are local by construction.
        return True
    host = str(address[0])
    return host in {"127.0.0.1", "::1", "localhost", ""}


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Run the test with default settings and every external egress blocked.

    Args:
        monkeypatch: Fixture used to clear env vars and patch the socket.
        tmp_path: Working directory the default relative SQLite URL resolves in.

    Yields:
        Control to the test body.
    """
    for name in _EXTERNAL_SERVICE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # The default database_url is relative ("sqlite:///./autodev.db"), so the
    # database file lands in the temp directory rather than the repo root.
    monkeypatch.chdir(tmp_path)

    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        """Reject any connection leaving the local machine.

        Args:
            self: The socket being connected.
            address: Target address.

        Returns:
            The real connection result for loopback targets.

        Raises:
            ExternalNetworkAttempt: For any non-loopback target.
        """
        if not _is_loopback(address):
            raise ExternalNetworkAttempt(
                f"local-first mode attempted an external connection to {address!r}"
            )
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    reset_settings_cache()
    reset_store_cache()
    reset_event_bus_for_tests()
    reset_event_store_for_tests()
    try:
        yield
    finally:
        reset_settings_cache()
        reset_store_cache()
        reset_event_bus_for_tests()
        reset_event_store_for_tests()


def test_defaults_select_sqlite_stub_provider_and_in_memory_bus(offline: None) -> None:
    """With no configuration at all, nothing points at an external service."""
    settings = get_settings()

    assert settings.database_url.startswith("sqlite://")
    assert settings.llm_provider == "stub"
    assert settings.autodev_event_bus == "inmemory"
    assert settings.autodev_redis_url == ""
    assert settings.otel_exporter_otlp_endpoint == ""


def test_flow_runs_end_to_end_without_leaving_the_machine(offline: None) -> None:
    """A declarative flow completes on defaults with external egress blocked."""
    callables = CallableRegistry()
    callables.register("autodev/skill-echo", lambda payload: {"echo": payload})
    engine = FlowEngine(handlers=build_default_handlers(callables=callables))
    engine.registry.register_raw(
        {
            "schemaVersion": "1",
            "id": "autodev/flow-local-first",
            "version": "1.0.0",
            "hostApi": ">=2.0 <3.0",
            "nodes": [{"id": "only", "type": "skill", "ref": "autodev/skill-echo"}],
            "edges": [],
        }
    )

    run = engine.start_run("autodev/flow-local-first", input={"x": 1})

    assert run.status == "completed"
    steps = engine.runs.list_steps(run.run_id)
    assert [step.node_id for step in steps] == ["only"]


def test_the_offline_guard_itself_rejects_external_connections(offline: None) -> None:
    """The guard must actually fire, or the tests above would prove nothing."""
    with pytest.raises(ExternalNetworkAttempt):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.1)
            sock.connect(("93.184.216.34", 80))
