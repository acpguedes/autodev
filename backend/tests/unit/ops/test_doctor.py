"""Tests for backend/ops/doctor.py (E34-S2-T3)."""

from __future__ import annotations

import socket

import pytest

from backend.config.settings import reset_settings_cache
from backend.ops.doctor import diagnostics_ok, run_diagnostics


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_run_diagnostics_all_pass_in_local_profile(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "autodev.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AUTODEV_PROFILE", "local")
    monkeypatch.setenv("AUTODEV_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AUTODEV_PORT", "8000")
    reset_settings_cache()

    checks = run_diagnostics()

    names = [c.name for c in checks]
    assert names == ["settings", "port", "project_root", "database", "storage_backend"]
    assert diagnostics_ok(checks)


def test_run_diagnostics_skips_dependent_checks_when_settings_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTODEV_PROFILE", "prod")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./autodev.db")
    reset_settings_cache()

    checks = run_diagnostics()

    assert [c.name for c in checks] == ["settings"]
    assert checks[0].status == "fail"
    assert not diagnostics_ok(checks)


def test_database_check_fails_for_unwritable_sqlite_parent(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_parent = tmp_path / "does-not-exist" / "autodev.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{missing_parent}")
    monkeypatch.setenv("AUTODEV_PROFILE", "local")
    monkeypatch.setenv("AUTODEV_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    reset_settings_cache()

    checks = run_diagnostics()

    database_check = next(c for c in checks if c.name == "database")
    assert database_check.status == "fail"
    assert not diagnostics_ok(checks)


def test_port_check_fails_when_port_already_bound(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    bound_port = server.getsockname()[1]
    try:
        db_path = tmp_path / "autodev.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("AUTODEV_PROFILE", "local")
        monkeypatch.setenv("AUTODEV_ARTIFACT_DIR", str(tmp_path / "artifacts"))
        monkeypatch.setenv("AUTODEV_HOST", "127.0.0.1")
        monkeypatch.setenv("AUTODEV_PORT", str(bound_port))
        reset_settings_cache()

        checks = run_diagnostics()

        port_check = next(c for c in checks if c.name == "port")
        assert port_check.status == "fail"
    finally:
        server.close()
