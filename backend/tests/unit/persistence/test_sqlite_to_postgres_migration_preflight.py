"""E58-S1 — CLI command, preflight, and dry-run tests.

Preflight/dry-run cases that only need a SQLite source run unconditionally.
Cases that need a real, empty PostgreSQL destination skip automatically
unless ``AUTODEV_TEST_POSTGRES_URL`` is set, mirroring
``backend/tests/persistence_contract/backends.py`` (E56) — a fresh database
is provisioned and dropped per test so "destination empty" means something.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.persistence.sqlite_adapter import SQLiteStore
from backend.persistence.sqlite_to_postgres.plan import build_dry_run_plan
from backend.persistence.sqlite_to_postgres.preflight import run_preflight
from backend.tests.persistence_contract.backends import (
    drop_postgres_database,
    postgres_admin_url,
    provision_postgres_database,
)
from backend.tests.postgres_gate import REQUIRE_POSTGRES_ENV, require_mark

_INVALID_DEST_URL = "not-a-postgres-url"


def _seed_sqlite(db_path: Path) -> SQLiteStore:
    """Build a SQLite store with one session, for row-count assertions."""
    store = SQLiteStore(f"sqlite:///{db_path}")
    store.create_session(
        session_id="sess-1",
        goal="prove E58 preflight works",
        plan=["step one"],
        artifacts={},
    )
    return store


def _source_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


def test_preflight_fails_when_source_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.db"
    report = run_preflight(_source_url(missing), _INVALID_DEST_URL)
    assert not report.passed
    assert any("not found" in e for e in report.errors)


def test_preflight_rejects_non_postgres_destination(tmp_path: Path) -> None:
    db_path = tmp_path / "source.db"
    _seed_sqlite(db_path)
    report = run_preflight(_source_url(db_path), _INVALID_DEST_URL)
    assert not report.passed
    assert any("postgresql://" in e for e in report.errors)


def test_preflight_fails_on_unknown_source_table(tmp_path: Path) -> None:
    db_path = tmp_path / "source.db"
    _seed_sqlite(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE totally_unexpected_table (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()

    report = run_preflight(_source_url(db_path), _INVALID_DEST_URL)
    assert not report.passed
    assert "totally_unexpected_table" in report.unknown_source_tables
    assert any("totally_unexpected_table" in e for e in report.errors)


def test_preflight_fails_on_stale_source_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "source.db"
    _seed_sqlite(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE schema_version SET version = version - 1 WHERE namespace = 'store'"
        )
        conn.commit()
    finally:
        conn.close()

    report = run_preflight(_source_url(db_path), _INVALID_DEST_URL)
    assert not report.passed
    assert any("store" in e and "version" in e for e in report.errors)


def test_preflight_never_mutates_source(tmp_path: Path) -> None:
    db_path = tmp_path / "source.db"
    _seed_sqlite(db_path)
    before = db_path.read_bytes()

    run_preflight(_source_url(db_path), _INVALID_DEST_URL)

    assert db_path.read_bytes() == before


def test_dry_run_reports_source_row_counts_without_writing(tmp_path: Path) -> None:
    db_path = tmp_path / "source.db"
    _seed_sqlite(db_path)
    before = db_path.read_bytes()

    plan = build_dry_run_plan(_source_url(db_path), _INVALID_DEST_URL)

    assert db_path.read_bytes() == before
    sessions_plan = next(t for t in plan.tables if t.table == "sessions")
    assert sessions_plan.source_rows == 1
    assert plan.total_source_rows >= 1
    assert not plan.destination_schema_applied


def test_dry_run_reports_unresolvable_source(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.db"
    plan = build_dry_run_plan(_source_url(missing), _INVALID_DEST_URL)
    assert not plan.preflight.passed
    assert plan.tables == ()


_POSTGRES_URL = postgres_admin_url()


@pytest.fixture
def empty_postgres() -> str:
    """Yield a fresh, empty PostgreSQL database URL, dropped after the test."""
    admin_url = _POSTGRES_URL
    assert admin_url is not None
    database_url = provision_postgres_database(admin_url)
    try:
        yield database_url
    finally:
        drop_postgres_database(admin_url, database_url)


@pytest.mark.slow
@require_mark(
    bool(_POSTGRES_URL),
    require_env=REQUIRE_POSTGRES_ENV,
    reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E58)",
)
def test_preflight_passes_against_empty_destination(
    tmp_path: Path, empty_postgres: str
) -> None:
    db_path = tmp_path / "source.db"
    _seed_sqlite(db_path)

    report = run_preflight(_source_url(db_path), empty_postgres)

    assert report.passed, report.errors
    assert not report.destination_has_data


@pytest.mark.slow
@require_mark(
    bool(_POSTGRES_URL),
    require_env=REQUIRE_POSTGRES_ENV,
    reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E58)",
)
def test_preflight_reports_nonempty_destination_and_confirm_flag(
    tmp_path: Path, empty_postgres: str
) -> None:
    from backend.persistence.postgres_adapter import PostgresStore

    db_path = tmp_path / "source.db"
    _seed_sqlite(db_path)
    dest_store = PostgresStore(empty_postgres)
    dest_store.create_session(
        session_id="dest-sess",
        goal="already here",
        plan=[],
        artifacts={},
    )

    refused = run_preflight(_source_url(db_path), empty_postgres)
    assert not refused.passed
    assert refused.destination_has_data

    confirmed = run_preflight(
        _source_url(db_path), empty_postgres, confirm_nonempty_destination=True
    )
    assert confirmed.passed, confirmed.errors
    assert confirmed.destination_has_data
