"""E58-S3 — auxiliary sources (step state, artifacts) and reconciliation.

Every test here needs a real destination PostgreSQL database, so the whole
module skips automatically unless ``AUTODEV_TEST_POSTGRES_URL`` is set (see
``backend/tests/persistence_contract/backends.py``, E56).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

from backend.artifacts.store import ArtifactKind, ArtifactPointer, LocalArtifactStore
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.persistence.sqlite_to_postgres.artifacts import find_dangling_artifact_pointers
from backend.persistence.sqlite_to_postgres.connections import open_dest_connection, open_source_connection
from backend.persistence.sqlite_to_postgres.reconcile import reconcile_all_tables
from backend.persistence.sqlite_to_postgres.runner import run_migration
from backend.tests.persistence_contract.backends import (
    drop_postgres_database,
    postgres_admin_url,
    provision_postgres_database,
)
from backend.tests.postgres_gate import REQUIRE_POSTGRES_ENV, require_mark

_POSTGRES_URL = postgres_admin_url()

pytestmark = [
    pytest.mark.slow,
    require_mark(
        bool(_POSTGRES_URL),
        require_env=REQUIRE_POSTGRES_ENV,
        reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E58)",
    ),
]


@pytest.fixture(autouse=True)
def _writable_artifact_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the ambient artifact store at a writable tmp directory.

    ``run_migration`` looks up the artifact store via
    :func:`backend.artifacts.store.get_artifact_store` for the dangling
    pointer check (E58-S3-T2). Its default (``/data/artifacts``) is a
    container-oriented path that is not writable here, so every test in this
    module needs a real, writable directory instead.
    """
    from backend.config.settings import reset_settings_cache

    monkeypatch.setenv("AUTODEV_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def empty_postgres() -> Iterator[str]:
    """Yield a fresh, empty PostgreSQL database URL, dropped after the test."""
    admin_url = _POSTGRES_URL
    assert admin_url is not None
    database_url = provision_postgres_database(admin_url)
    try:
        yield database_url
    finally:
        drop_postgres_database(admin_url, database_url)


def _seed_source(db_path: Path) -> None:
    store = SQLiteStore(f"sqlite:///{db_path}")
    store.create_session(session_id="sess-a", goal="reconcile me", plan=[], artifacts={})
    store.create_run(
        run_id="run-a",
        session_id="sess-a",
        status="completed",
        run_type="chat",
        current_state="done",
        trigger_message="hi",
        results=[],
        steps=[],
    )
    store.append_messages("sess-a", "run-a", [{"role": "user", "content": "hello"}])


def _migrate(db_path: Path, dest_url: str):
    return run_migration(f"sqlite:///{db_path}", dest_url)


def test_reconciliation_passes_after_a_clean_migration(tmp_path: Path, empty_postgres: str) -> None:
    db_path = tmp_path / "source.db"
    _seed_source(db_path)

    result = _migrate(db_path, empty_postgres)

    assert result.preflight.passed, result.preflight.errors
    assert result.safe_to_cut_over, result.reconciliation
    by_table = {t.table: t for t in result.reconciliation.tables}
    assert by_table["sessions"].matched
    assert by_table["sessions"].source_count == by_table["sessions"].dest_count == 1


def test_reconciliation_detects_a_deliberately_corrupted_row(tmp_path: Path, empty_postgres: str) -> None:
    import psycopg

    db_path = tmp_path / "source.db"
    _seed_source(db_path)
    _migrate(db_path, empty_postgres)

    from backend.persistence.tenancy import set_postgres_tenant

    conn = psycopg.connect(empty_postgres)
    try:
        set_postgres_tenant(conn, "default")
        conn.execute("UPDATE sessions SET goal = 'corrupted' WHERE id = %s", ("sess-a",))
        conn.commit()
    finally:
        conn.close()

    source_conn = open_source_connection(f"sqlite:///{db_path}")
    dest_conn = open_dest_connection(empty_postgres)
    try:
        report = reconcile_all_tables(source_conn, dest_conn)
    finally:
        source_conn.close()
        dest_conn.close()

    assert not report.passed
    sessions = next(t for t in report.tables if t.table == "sessions")
    assert not sessions.matched
    assert sessions.mismatched_digests == 1
    assert sessions.source_count == sessions.dest_count == 1  # counts match; only content differs


def test_step_state_migration_moves_legacy_rows_to_destination(
    tmp_path: Path, empty_postgres: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.persistence.sqlite_adapter.plan_store import SQLitePlanStore

    db_path = tmp_path / "source.db"
    store = SQLiteStore(f"sqlite:///{db_path}")
    store.create_session(session_id="sess-a", goal="has a plan", plan=[], artifacts={})
    SQLitePlanStore(db_path=db_path).upsert_plan("sess-a", [])

    legacy_path = tmp_path / "legacy_step_state.db"
    legacy = sqlite3.connect(legacy_path)
    try:
        legacy.execute(
            "CREATE TABLE plan_step_state (tenant_id TEXT, session_id TEXT, step_index INTEGER, "
            "content TEXT, state TEXT, updated_at TEXT)"
        )
        legacy.execute(
            "INSERT INTO plan_step_state VALUES ('default', 'sess-a', 0, 'do the thing', "
            "'pending', '2026-01-01T00:00:00+00:00')"
        )
        legacy.commit()
    finally:
        legacy.close()

    monkeypatch.setenv("AUTODEV_PLAN_STEP_STATE_DB", str(legacy_path))

    result = _migrate(db_path, empty_postgres)

    assert result.step_state is not None
    assert result.step_state.rows_written == 1
    assert result.step_state.rows_unresolved == 0

    import psycopg

    conn = psycopg.connect(empty_postgres)
    try:
        from backend.persistence.tenancy import set_postgres_tenant

        set_postgres_tenant(conn, "default")
        row = conn.execute(
            "SELECT content, state FROM plan_step_state WHERE session_id = %s AND step_index = 0",
            ("sess-a",),
        ).fetchone()
        conn.rollback()
    finally:
        conn.close()

    assert row == ("do the thing", "pending")


def test_dangling_artifact_pointer_is_reported_not_dropped(tmp_path: Path, empty_postgres: str) -> None:
    from backend.artifacts.pointers import ArtifactPointerStore

    db_path = tmp_path / "source.db"
    store = SQLiteStore(f"sqlite:///{db_path}")
    pointer_store = ArtifactPointerStore(store=store)
    pointer_store.record(
        ArtifactPointer(
            bucket="patches", object_key="never-actually-written.diff", sha256="deadbeef", size_bytes=0, content_type="text/plain"
        ),
        kind=ArtifactKind.PATCH,
    )

    result = _migrate(db_path, empty_postgres)
    assert result.safe_to_cut_over, result.reconciliation  # the row migrated; only its object is missing

    artifact_store = LocalArtifactStore(tmp_path / "artifacts")  # deliberately empty
    dest_conn = open_dest_connection(empty_postgres)
    try:
        dangling = find_dangling_artifact_pointers(dest_conn, artifact_store)
    finally:
        dest_conn.close()

    assert len(dangling) == 1
    assert dangling[0].bucket == "patches"
    assert dangling[0].object_key == "never-actually-written.diff"
