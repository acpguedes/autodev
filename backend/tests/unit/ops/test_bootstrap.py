"""Tests for backend/ops/bootstrap.py (E34-S2-T1)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.config.settings import reset_settings_cache
from backend.ops.bootstrap import bootstrap
from backend.persistence.database import reset_store_cache


@pytest.fixture(autouse=True)
def _reset_caches(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Isolate AUTODEV_HOME and cwd: bootstrap() fails closed on any doctor
    # check failing, and the global_home/legacy_database checks (E61-S1)
    # would otherwise see whatever local dev state sits beside the repo
    # root.
    monkeypatch.setenv("AUTODEV_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    reset_store_cache()
    yield
    reset_settings_cache()
    reset_store_cache()


def test_bootstrap_initializes_store_when_preflight_passes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "autodev.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AUTODEV_PROFILE", "local")
    monkeypatch.setenv("AUTODEV_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    reset_settings_cache()

    result = bootstrap()

    assert result.status == "ok"
    assert result.profile == "local"
    assert db_path.exists()
    payload = result.as_dict()
    assert payload["status"] == "ok"
    assert "profile" in payload


def test_bootstrap_is_idempotent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "autodev.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AUTODEV_PROFILE", "local")
    monkeypatch.setenv("AUTODEV_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    reset_settings_cache()

    first = bootstrap()
    second = bootstrap()

    assert first.status == second.status == "ok"


def test_bootstrap_fails_closed_when_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTODEV_PROFILE", "prod")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./autodev.db")
    reset_settings_cache()

    result = bootstrap()

    assert result.status == "fail"
    assert result.profile == ""
    assert any(check.status == "fail" for check in result.checks)
