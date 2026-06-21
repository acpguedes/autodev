"""Tests for U6 — Agents Registry API + CLI.

Covers:
* GET /agents lists the 8 defaults + the 3 specialized agents (security/refactor/docs).
* GET /agents/{name} returns details; schema present for agents with metadata_model.
* GET /agents/unknown_xyz returns 404.
* CLI ``autodev agents list`` prints the expected names.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from backend.persistence.database import reset_store_cache


# ---------------------------------------------------------------------------
# Isolation fixture for CLI tests (mirrors existing test_cli.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    database_path = tmp_path / "cli.db"
    config_path = tmp_path / "autodev.config.json"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(config_path))
    monkeypatch.chdir(tmp_path)
    reset_store_cache()
    yield
    reset_store_cache()


# ---------------------------------------------------------------------------
# API fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    from backend.api.main import app  # noqa: PLC0415
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /agents — list
# ---------------------------------------------------------------------------


_EXPECTED_DEFAULTS = {
    "planner",
    "navigator",
    "analyzer",
    "architect",
    "coder",
    "devops",
    "validator",
    "responder",
}

_EXPECTED_SPECIALIZED = {"security", "refactor", "docs"}
_ALL_EXPECTED = _EXPECTED_DEFAULTS | _EXPECTED_SPECIALIZED


def test_list_agents_returns_200(client: TestClient) -> None:
    resp = client.get("/agents")
    assert resp.status_code == 200


def test_list_agents_is_list(client: TestClient) -> None:
    resp = client.get("/agents")
    assert isinstance(resp.json(), list)


def test_list_agents_includes_eight_defaults(client: TestClient) -> None:
    resp = client.get("/agents")
    names = {item["name"] for item in resp.json()}
    for default in _EXPECTED_DEFAULTS:
        assert default in names, f"Default agent {default!r} missing from /agents"


def test_list_agents_includes_specialized(client: TestClient) -> None:
    resp = client.get("/agents")
    names = {item["name"] for item in resp.json()}
    for spec in _EXPECTED_SPECIALIZED:
        assert spec in names, f"Specialized agent {spec!r} missing from /agents"


def test_list_agents_items_have_required_fields(client: TestClient) -> None:
    resp = client.get("/agents")
    for item in resp.json():
        assert "name" in item
        assert "has_metadata_contract" in item
        assert "source" in item


def test_list_agents_defaults_marked_as_default_source(client: TestClient) -> None:
    resp = client.get("/agents")
    by_name = {item["name"]: item for item in resp.json()}
    for name in _EXPECTED_DEFAULTS:
        assert by_name[name]["source"] == "default", (
            f"Agent {name!r} should have source='default'"
        )


# ---------------------------------------------------------------------------
# GET /agents/{name} — describe
# ---------------------------------------------------------------------------


def test_describe_planner_returns_200(client: TestClient) -> None:
    resp = client.get("/agents/planner")
    assert resp.status_code == 200


def test_describe_planner_has_contract(client: TestClient) -> None:
    resp = client.get("/agents/planner")
    body = resp.json()
    assert body["has_metadata_contract"] is True


def test_describe_planner_returns_schema(client: TestClient) -> None:
    resp = client.get("/agents/planner")
    body = resp.json()
    assert body["metadata_schema"] is not None
    assert "properties" in body["metadata_schema"] or "title" in body["metadata_schema"]


def test_describe_security_agent_returns_200(client: TestClient) -> None:
    resp = client.get("/agents/security")
    assert resp.status_code == 200


def test_describe_unknown_agent_returns_404(client: TestClient) -> None:
    resp = client.get("/agents/no_such_agent_xyz")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# CLI — autodev agents list
# ---------------------------------------------------------------------------


def test_cli_agents_list_exit_zero(
    isolated_runtime: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backend.cli import build_parser  # noqa: PLC0415
    parser = build_parser()
    ns = parser.parse_args(["agents", "list"])
    code = ns.handler(ns)
    assert code == 0


def test_cli_agents_list_contains_defaults(
    isolated_runtime: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backend.cli import build_parser  # noqa: PLC0415
    parser = build_parser()
    ns = parser.parse_args(["agents", "list"])
    ns.handler(ns)
    out = capsys.readouterr().out
    data = json.loads(out)
    names = {item["name"] for item in data}
    for default in _EXPECTED_DEFAULTS:
        assert default in names


def test_cli_agents_list_contains_specialized(
    isolated_runtime: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backend.cli import build_parser  # noqa: PLC0415
    parser = build_parser()
    ns = parser.parse_args(["agents", "list"])
    ns.handler(ns)
    out = capsys.readouterr().out
    data = json.loads(out)
    names = {item["name"] for item in data}
    for spec in _EXPECTED_SPECIALIZED:
        assert spec in names
