"""Tests for the validation API router and CLI plugin — U15."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.cli import build_parser

client = TestClient(app)


def test_run_disabled_returns_skipped(monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_ENABLE_SANDBOX", raising=False)
    response = client.post("/validation/run", json={"command": ["pytest", "-q"]})
    assert response.status_code == 200
    body = response.json()
    assert body["skipped"] is True
    assert body["backend"] == "disabled"
    assert body["returncode"] == 0

    # The result is retrievable by job_id.
    follow_up = client.get(f"/validation/{body['job_id']}")
    assert follow_up.status_code == 200
    assert follow_up.json()["job_id"] == body["job_id"]


def test_run_empty_command_rejected() -> None:
    response = client.post("/validation/run", json={"command": []})
    assert response.status_code == 400


def test_get_unknown_job_returns_404() -> None:
    assert client.get("/validation/does-not-exist").status_code == 404


def test_cli_validate_run_disabled(monkeypatch, capsys) -> None:
    monkeypatch.delenv("AUTODEV_ENABLE_SANDBOX", raising=False)
    parser = build_parser()
    args = parser.parse_args(["validate", "run", "python", "-c", "print(1)"])
    exit_code = args.handler(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert '"skipped": true' in out
    assert '"backend": "disabled"' in out
