"""Tests for the three plugin auto-discovery seams (U1).

Each seam must:
* be importable without side effects;
* be a safe no-op when its watched directory is empty;
* expose the correct public interface.
"""

from __future__ import annotations

import argparse

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Router seam
# ---------------------------------------------------------------------------


def test_include_all_routers_importable() -> None:
    from backend.api.routers import include_all_routers  # noqa: F401

    assert callable(include_all_routers)


def test_include_all_routers_noop_on_empty_dir() -> None:
    """Calling include_all_routers on a fresh FastAPI app must not raise."""
    from backend.api.routers import include_all_routers

    app = FastAPI()
    # Should complete without raising even when no router modules exist yet.
    include_all_routers(app)


def test_health_endpoint_still_responds() -> None:
    """The real app /health endpoint must return 200 after the seam is added."""
    from backend.api.main import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Agent registry seam
# ---------------------------------------------------------------------------


def test_register_agent_importable() -> None:
    from backend.agents.registry import discover_agents, register_agent  # noqa: F401

    assert callable(register_agent)
    assert callable(discover_agents)


def test_discover_agents_empty_by_default() -> None:
    """When nothing is registered, discover_agents returns an empty dict."""
    from backend.agents import registry as reg

    # Snapshot the current registry so we don't pollute other tests.
    original = dict(reg._REGISTRY)
    reg._REGISTRY.clear()
    try:
        result = reg.discover_agents()
        assert result == {}
    finally:
        reg._REGISTRY.update(original)


def test_register_and_discover_agent() -> None:
    """Registering a dummy agent makes it appear in discover_agents()."""
    from backend.agents import registry as reg

    original = dict(reg._REGISTRY)
    reg._REGISTRY.clear()
    try:

        @reg.register_agent("dummy")
        class _DummyAgent:
            name = "dummy"

            def run(self, context):  # pragma: no cover
                pass

        found = reg.discover_agents()
        assert "dummy" in found
        assert isinstance(found["dummy"], _DummyAgent)
    finally:
        reg._REGISTRY.clear()
        reg._REGISTRY.update(original)


def test_register_and_discover_agent_with_project_root(tmp_path) -> None:
    """Agents that accept project_root receive it during discover_agents()."""
    from pathlib import Path

    from backend.agents import registry as reg

    original = dict(reg._REGISTRY)
    reg._REGISTRY.clear()
    try:
        received: list[Path] = []

        @reg.register_agent("root-aware")
        class _RootAwareAgent:
            name = "root-aware"

            def __init__(self, project_root=None):
                received.append(project_root)

            def run(self, context):  # pragma: no cover
                pass

        reg.discover_agents(project_root=tmp_path)
        assert received == [tmp_path]
    finally:
        reg._REGISTRY.clear()
        reg._REGISTRY.update(original)


def test_discover_agents_skips_bad_agent() -> None:
    """A broken agent constructor is logged and skipped; others still return."""
    from backend.agents import registry as reg

    original = dict(reg._REGISTRY)
    reg._REGISTRY.clear()
    try:

        @reg.register_agent("broken")
        class _BrokenAgent:
            def __init__(self):
                raise RuntimeError("boom")

        @reg.register_agent("good")
        class _GoodAgent:
            name = "good"

            def run(self, context):  # pragma: no cover
                pass

        found = reg.discover_agents()
        assert "broken" not in found
        assert "good" in found
    finally:
        reg._REGISTRY.clear()
        reg._REGISTRY.update(original)


# ---------------------------------------------------------------------------
# CLI plugin seam
# ---------------------------------------------------------------------------


def test_register_subcommands_importable() -> None:
    from backend.cli_plugins import register_subcommands  # noqa: F401

    assert callable(register_subcommands)


def test_register_subcommands_noop_on_empty_dir() -> None:
    """Calling register_subcommands on a fresh subparsers must not raise."""
    from backend.cli_plugins import register_subcommands

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    # Should complete without raising even when no plugin modules exist yet.
    register_subcommands(subparsers)
