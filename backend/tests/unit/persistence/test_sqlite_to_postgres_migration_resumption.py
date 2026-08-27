"""E58-S4-T1 — interrupted migration resumes without duplication; a full re-run is a no-op.

Needs a real destination PostgreSQL database; skips automatically unless
``AUTODEV_TEST_POSTGRES_URL`` is set (see
``backend/tests/persistence_contract/backends.py``, E56).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.persistence.sqlite_adapter import SQLiteStore
from backend.persistence.sqlite_to_postgres.connections import open_dest_connection, open_source_connection
from backend.persistence.sqlite_to_postgres.copy import copy_table
from backend.persistence.sqlite_to_postgres.runner import run_migration
from backend.persistence.tenancy import set_postgres_tenant
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
def _writable_artifact_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the ambient artifact store at a writable tmp directory (see E58-S3's test module)."""
    from backend.config.settings import reset_settings_cache

    monkeypatch.setenv("AUTODEV_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    reset_settings_cache()
    yield
    reset_settings_cache()


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


def _seed_source(db_path: Path) -> None:
    store = SQLiteStore(f"sqlite:///{db_path}")
    store.create_session(session_id="sess-a", goal="resume me", plan=[], artifacts={})
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
    store.append_messages("sess-a", "run-a", [{"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}])


def test_interrupted_migration_resumes_without_duplication(tmp_path: Path, empty_postgres: str) -> None:
    from backend.persistence.postgres_adapter import PostgresStore

    db_path = tmp_path / "source.db"
    _seed_source(db_path)

    # Simulate a crash after the destination schema was applied and only the
    # first table (sessions) had been copied -- exactly the kind of partial
    # state an interruption between two per-table commits
    # (copy.copy_table commits once per table) would leave behind.
    PostgresStore(empty_postgres)
    source_conn = open_source_connection(f"sqlite:///{db_path}")
    dest_conn = open_dest_connection(empty_postgres)
    try:
        copy_table(source_conn, dest_conn, "sessions")
    finally:
        source_conn.close()
        dest_conn.close()

    # Resume: run the full migration again from scratch. Preflight sees a
    # non-empty destination (the partial "sessions" row), so the operator
    # must confirm -- exactly the real resumption workflow.
    result = run_migration(f"sqlite:///{db_path}", empty_postgres, confirm_nonempty_destination=True)

    assert result.preflight.passed, result.preflight.errors
    assert result.safe_to_cut_over, result.reconciliation

    conn = open_dest_connection(empty_postgres)
    try:
        set_postgres_tenant(conn, "default")
        session_count = conn.execute("SELECT COUNT(*) FROM sessions WHERE id = %s", ("sess-a",)).fetchone()[0]
        message_count = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = %s", ("sess-a",)).fetchone()[0]
        conn.rollback()
    finally:
        conn.close()

    assert session_count == 1  # no duplicate from the resumed run re-attempting it
    assert message_count == 2  # the tables the interrupted run never reached still migrated


def test_full_rerun_after_completion_is_a_no_op(tmp_path: Path, empty_postgres: str) -> None:
    db_path = tmp_path / "source.db"
    _seed_source(db_path)

    first = run_migration(f"sqlite:///{db_path}", empty_postgres)
    assert first.safe_to_cut_over, first.reconciliation

    second = run_migration(f"sqlite:///{db_path}", empty_postgres, confirm_nonempty_destination=True)
    assert second.safe_to_cut_over, second.reconciliation

    by_table = {t.table: t for t in second.reconciliation.tables}
    assert by_table["sessions"].source_count == by_table["sessions"].dest_count == 1
    assert by_table["messages"].source_count == by_table["messages"].dest_count == 2
