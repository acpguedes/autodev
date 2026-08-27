"""E58-S2 — ordered copy, identity preservation, sequence adjustment, and type conversion.

Every test here needs a real destination PostgreSQL database (the copy
engine writes through psycopg, not a fake), so the whole module skips
automatically unless ``AUTODEV_TEST_POSTGRES_URL`` is set, mirroring
``backend/tests/persistence_contract/backends.py`` (E56) -- a fresh database
is provisioned and dropped per test.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

from backend.persistence.sqlite_adapter import SQLiteStore
from backend.persistence.sqlite_to_postgres.connections import open_source_connection
from backend.persistence.sqlite_to_postgres.copy import copy_all_tables
from backend.persistence.tenancy import set_postgres_tenant
from backend.secret_store.contracts import SecretReference
from backend.secret_store.store import SecretStore
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
    """Build a source SQLite database covering the copy engine's edge cases:
    a FK chain (sessions -> runs -> messages), two distinct tenants, a
    boolean column, and an encrypted secret.
    """
    store = SQLiteStore(f"sqlite:///{db_path}")
    store.create_session(
        session_id="sess-a", goal="tenant a's session", plan=["step"], artifacts={}, tenant_id="tenant-a"
    )
    store.create_run(
        run_id="run-a",
        session_id="sess-a",
        status="completed",
        run_type="chat",
        current_state="done",
        trigger_message="hello",
        results=[{"ok": True}],
        steps=[],
        tenant_id="tenant-a",
    )
    store.append_messages(
        "sess-a", "run-a", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}],
        tenant_id="tenant-a",
    )
    store.create_session(
        session_id="sess-b", goal="tenant b's session", plan=[], artifacts={}, tenant_id="tenant-b"
    )

    SecretStore(store=store).create(
        SecretReference(tenant_id="tenant-a", project="default", name="git-token"),
        "super-secret-ciphertext==",
    )

    raw = sqlite3.connect(db_path)
    try:
        raw.execute(
            "INSERT INTO score_snapshot_promotions "
            "(policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at) "
            "VALUES ('policy-1', 'snap-1', '', 1, 'good enough', '2026-01-01T00:00:00+00:00')"
        )
        raw.execute(
            "INSERT INTO score_snapshot_promotions "
            "(policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at) "
            "VALUES ('policy-1', 'snap-2', 'snap-1', 0, 'worse', '2026-01-02T00:00:00+00:00')"
        )
        raw.commit()
    finally:
        raw.close()


def _migrate(db_path: Path, dest_url: str) -> None:
    from backend.persistence.postgres_adapter import PostgresStore

    PostgresStore(dest_url)  # applies the destination schema (ADR-026 decision 5)
    source_conn = open_source_connection(f"sqlite:///{db_path}")
    dest_conn = __import__("psycopg").connect(dest_url)
    try:
        copy_all_tables(source_conn, dest_conn)
    finally:
        source_conn.close()
        dest_conn.close()


def test_copy_preserves_identity_and_row_counts(tmp_path: Path, empty_postgres: str) -> None:
    import psycopg

    db_path = tmp_path / "source.db"
    _seed_source(db_path)

    _migrate(db_path, empty_postgres)

    conn = psycopg.connect(empty_postgres)
    try:
        set_postgres_tenant(conn, "tenant-a")
        row = conn.execute("SELECT id, goal FROM sessions WHERE id = %s", ("sess-a",)).fetchone()
        assert row == ("sess-a", "tenant a's session")
        count = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = %s", ("sess-a",)).fetchone()
        assert count is not None
        assert count[0] == 2
        conn.rollback()
    finally:
        conn.close()


def test_copy_scopes_rows_to_their_own_tenant_under_rls(tmp_path: Path, empty_postgres: str) -> None:
    import psycopg

    db_path = tmp_path / "source.db"
    _seed_source(db_path)

    _migrate(db_path, empty_postgres)

    conn = psycopg.connect(empty_postgres)
    try:
        set_postgres_tenant(conn, "tenant-a")
        visible_a = {r[0] for r in conn.execute("SELECT id FROM sessions").fetchall()}
        conn.rollback()
        set_postgres_tenant(conn, "tenant-b")
        visible_b = {r[0] for r in conn.execute("SELECT id FROM sessions").fetchall()}
        conn.rollback()
    finally:
        conn.close()

    assert visible_a == {"sess-a"}
    assert visible_b == {"sess-b"}


def test_copy_adjusts_sequence_past_migrated_maximum(tmp_path: Path, empty_postgres: str) -> None:
    from backend.persistence.postgres_adapter import PostgresStore

    db_path = tmp_path / "source.db"
    _seed_source(db_path)

    _migrate(db_path, empty_postgres)

    dest_store = PostgresStore(empty_postgres)
    dest_store.append_messages(
        "sess-a", "run-a", [{"role": "user", "content": "new message post-migration"}], tenant_id="tenant-a"
    )

    import psycopg

    conn = psycopg.connect(empty_postgres)
    try:
        set_postgres_tenant(conn, "tenant-a")
        ids = [r[0] for r in conn.execute("SELECT id FROM messages ORDER BY id").fetchall()]
        conn.rollback()
    finally:
        conn.close()

    assert len(ids) == len(set(ids)), f"colliding message ids after migration: {ids}"


def test_copy_carries_secret_ciphertext_unchanged(tmp_path: Path, empty_postgres: str) -> None:
    import psycopg

    db_path = tmp_path / "source.db"
    _seed_source(db_path)

    _migrate(db_path, empty_postgres)

    conn = psycopg.connect(empty_postgres)
    try:
        set_postgres_tenant(conn, "tenant-a")
        row = conn.execute(
            "SELECT ciphertext FROM secrets WHERE tenant_id = %s AND name = %s",
            ("tenant-a", "git-token"),
        ).fetchone()
        conn.rollback()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == "super-secret-ciphertext=="


def test_copy_coerces_sqlite_integer_booleans_to_postgres_boolean(
    tmp_path: Path, empty_postgres: str
) -> None:
    import psycopg

    db_path = tmp_path / "source.db"
    _seed_source(db_path)

    _migrate(db_path, empty_postgres)

    conn = psycopg.connect(empty_postgres)
    try:
        rows: dict[str, bool] = dict(
            conn.execute(
                "SELECT snapshot_id, promoted FROM score_snapshot_promotions ORDER BY snapshot_id"
            ).fetchall()
        )
        conn.rollback()
    finally:
        conn.close()

    assert rows == {"snap-1": True, "snap-2": False}


def test_copy_is_idempotent_on_rerun(tmp_path: Path, empty_postgres: str) -> None:
    import psycopg

    db_path = tmp_path / "source.db"
    _seed_source(db_path)

    _migrate(db_path, empty_postgres)

    source_conn = open_source_connection(f"sqlite:///{db_path}")
    dest_conn = psycopg.connect(empty_postgres)
    try:
        results = copy_all_tables(source_conn, dest_conn)
    finally:
        source_conn.close()
        dest_conn.close()

    assert sum(r.rows_read for r in results) > 0  # rows were re-read (attempted), not skipped

    conn = psycopg.connect(empty_postgres)
    try:
        set_postgres_tenant(conn, "tenant-a")
        count = conn.execute("SELECT COUNT(*) FROM sessions WHERE tenant_id = %s", ("tenant-a",)).fetchone()
        conn.rollback()
    finally:
        conn.close()

    assert count is not None
    assert count[0] == 1  # no duplicate row from the second run
