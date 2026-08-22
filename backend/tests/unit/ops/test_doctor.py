"""Tests for backend/ops/doctor.py (E34-S2-T3, pgvector checks E48-S3)."""

from __future__ import annotations

import socket
import sys
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from backend.config.settings import reset_settings_cache
from backend.ops.doctor import diagnostics_ok, run_diagnostics


@pytest.fixture(autouse=True)
def _reset_settings() -> Iterator[None]:
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


# --- E48-S3: pgvector preflight checks -------------------------------------

_DEFAULT_HEALTHY_SCRIPT: list[tuple[str, Any]] = [
    ("SELECT 1 FROM pg_extension", (1,)),
    ("SHOW server_version_num", ("160004",)),
    ("'[1,2,3]'::vector", None),
    ("pg_index", (True,)),
    ("SELECT 1", (1,)),
]


class _FakeDoctorCursor:
    def __init__(self, result: Any) -> None:
        self._result = result

    def fetchone(self) -> Any:
        return self._result


class _FakeDoctorConnection:
    """Fake psycopg connection scripted by ordered (sql-substring, outcome) pairs.

    *outcome* is either a row tuple/``None`` to return from ``fetchone()``, or
    an ``Exception`` instance to raise from ``execute()``. The first matching
    substring (checked in list order) wins.
    """

    def __init__(self, script: list[tuple[str, Any]]) -> None:
        self._script = script

    def __enter__(self) -> "_FakeDoctorConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def close(self) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> _FakeDoctorCursor:
        for needle, outcome in self._script:
            if needle in sql:
                if isinstance(outcome, Exception):
                    raise outcome
                return _FakeDoctorCursor(outcome)
        return _FakeDoctorCursor(None)


def install_fake_doctor_psycopg(
    monkeypatch: pytest.MonkeyPatch,
    script: list[tuple[str, Any]] | None = None,
    connect_error: Exception | None = None,
) -> None:
    """Patch ``sys.modules['psycopg']`` for doctor.py's pgvector checks and ``_check_database``."""

    def connect(url: str, connect_timeout: int = 3) -> _FakeDoctorConnection:
        if connect_error is not None:
            raise connect_error
        return _FakeDoctorConnection(script if script is not None else _DEFAULT_HEALTHY_SCRIPT)

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))


def _set_prod_postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a full, otherwise-valid ``prod`` profile environment."""
    monkeypatch.setenv("AUTODEV_PROFILE", "prod")
    monkeypatch.setenv("DATABASE_URL", "postgresql://autodev:s3cret-test-pw@postgres:5432/autodev")
    monkeypatch.setenv("AUTODEV_JOB_BACKEND", "redis")
    monkeypatch.setenv("AUTODEV_EVENT_BUS", "redis")
    monkeypatch.setenv("AUTODEV_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AUTODEV_MINIO_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("AUTODEV_MINIO_ACCESS_KEY", "test-access-key")
    monkeypatch.setenv("AUTODEV_MINIO_SECRET_KEY", "test-secret-key")


def test_pgvector_checks_run_for_postgres_prod_profile_when_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All four pgvector checks are appended, right after ``database``, and pass."""
    _set_prod_postgres_env(monkeypatch)
    install_fake_doctor_psycopg(monkeypatch)
    reset_settings_cache()

    checks = run_diagnostics()

    assert [c.name for c in checks] == [
        "settings",
        "port",
        "project_root",
        "database",
        "postgres_server_version",
        "pgvector_extension_present",
        "pgvector_extension_usable",
        "pgvector_hnsw_index",
        "storage_backend",
    ]
    assert diagnostics_ok(checks)


def test_pgvector_checks_skipped_when_database_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When connectivity itself fails, the four pgvector checks are not attempted at all."""
    _set_prod_postgres_env(monkeypatch)
    install_fake_doctor_psycopg(monkeypatch, connect_error=RuntimeError("connection refused"))
    reset_settings_cache()

    checks = run_diagnostics()

    names = [c.name for c in checks]
    assert names == ["settings", "port", "project_root", "database", "storage_backend"]
    database_check = next(c for c in checks if c.name == "database")
    assert database_check.status == "fail"
    assert not diagnostics_ok(checks)


def test_postgres_server_version_check_fails_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server below PostgreSQL 16 fails the ``postgres_server_version`` check by itself."""
    _set_prod_postgres_env(monkeypatch)
    script = [s if s[0] != "SHOW server_version_num" else ("SHOW server_version_num", ("150004",)) for s in _DEFAULT_HEALTHY_SCRIPT]
    install_fake_doctor_psycopg(monkeypatch, script=script)
    reset_settings_cache()

    checks = run_diagnostics()

    check = next(c for c in checks if c.name == "postgres_server_version")
    assert check.status == "fail"
    assert "16" in check.detail


def test_pgvector_extension_present_check_fails_when_extension_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing ``vector`` extension fails the ``pgvector_extension_present`` check by itself."""
    _set_prod_postgres_env(monkeypatch)
    script = [s if s[0] != "SELECT 1 FROM pg_extension" else ("SELECT 1 FROM pg_extension", None) for s in _DEFAULT_HEALTHY_SCRIPT]
    install_fake_doctor_psycopg(monkeypatch, script=script)
    reset_settings_cache()

    checks = run_diagnostics()

    check = next(c for c in checks if c.name == "pgvector_extension_present")
    assert check.status == "fail"
    assert "CREATE EXTENSION vector" in check.detail


def test_pgvector_extension_usable_check_fails_when_type_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role that cannot use the ``vector`` type fails ``pgvector_extension_usable`` by itself."""
    _set_prod_postgres_env(monkeypatch)
    script = [
        s
        if s[0] != "'[1,2,3]'::vector"
        else ("'[1,2,3]'::vector", RuntimeError("permission denied for type vector"))
        for s in _DEFAULT_HEALTHY_SCRIPT
    ]
    install_fake_doctor_psycopg(monkeypatch, script=script)
    reset_settings_cache()

    checks = run_diagnostics()

    check = next(c for c in checks if c.name == "pgvector_extension_usable")
    assert check.status == "fail"


def test_pgvector_hnsw_index_check_fails_when_index_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid HNSW index fails the ``pgvector_hnsw_index`` check by itself."""
    _set_prod_postgres_env(monkeypatch)
    script = [s if s[0] != "pg_index" else ("pg_index", (False,)) for s in _DEFAULT_HEALTHY_SCRIPT]
    install_fake_doctor_psycopg(monkeypatch, script=script)
    reset_settings_cache()

    checks = run_diagnostics()

    check = next(c for c in checks if c.name == "pgvector_hnsw_index")
    assert check.status == "fail"
    assert "not valid" in check.detail
