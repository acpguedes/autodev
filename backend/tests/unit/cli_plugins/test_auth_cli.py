"""Contracts for the offline ``autodev auth service-key`` CLI (Task 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.cli import build_parser
from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture(autouse=True)
def _sqlite_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli_auth.db'}")
    reset_settings_cache()
    reset_store_cache()
    yield
    reset_settings_cache()
    reset_store_cache()


def _run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, object]:
    parser = build_parser()
    namespace = parser.parse_args(args)
    exit_code = namespace.handler(namespace)
    out = capsys.readouterr().out
    return exit_code, json.loads(out) if out.strip() else None


def test_service_key_create_prints_secret_once(capsys: pytest.CaptureFixture[str]) -> None:
    """Creating a service key prints the presented secret exactly once."""
    exit_code, payload = _run(
        [
            "auth",
            "service-key",
            "create",
            "--tenant-id",
            "tenant-a",
            "--subject",
            "ci",
            "--role",
            "operator",
            "--expires-in-days",
            "30",
        ],
        capsys,
    )
    assert exit_code == 0
    assert payload["key"].startswith("adk_live_")
    assert payload["roles"] == ["operator"]


def test_service_key_list_never_returns_a_secret(capsys: pytest.CaptureFixture[str]) -> None:
    """Listing service keys never includes a secret or its hash."""
    _run(
        [
            "auth",
            "service-key",
            "create",
            "--tenant-id",
            "tenant-a",
            "--subject",
            "ci",
            "--role",
            "operator",
            "--expires-in-days",
            "30",
        ],
        capsys,
    )
    exit_code, payload = _run(["auth", "service-key", "list", "--tenant-id", "tenant-a"], capsys)
    assert exit_code == 0
    assert len(payload) == 1
    assert "key" not in payload[0]
    assert "secretHash" not in payload[0]
    assert "secret_hash" not in payload[0]


def test_service_key_revoke_deactivates_it(capsys: pytest.CaptureFixture[str]) -> None:
    """Revoking a service key marks it inactive on the next listing."""
    _run(
        [
            "auth",
            "service-key",
            "create",
            "--tenant-id",
            "tenant-a",
            "--subject",
            "ci",
            "--role",
            "operator",
            "--expires-in-days",
            "30",
        ],
        capsys,
    )
    _, listing = _run(["auth", "service-key", "list", "--tenant-id", "tenant-a"], capsys)
    key_id = listing[0]["keyId"]

    exit_code, payload = _run(
        ["auth", "service-key", "revoke", "--tenant-id", "tenant-a", "--key-id", key_id],
        capsys,
    )
    assert exit_code == 0
    assert payload["revoked"] is True

    _, listing_after = _run(["auth", "service-key", "list", "--tenant-id", "tenant-a"], capsys)
    assert listing_after[0]["active"] is False
