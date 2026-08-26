"""Migration and restart-durability contract cases (E56-S3-T3).

Building ``sql_store`` already proves a from-empty migration run (S1). This
module adds: re-running migrations is a no-op (idempotent), a down/up round
trip leaves the schema usable, and data survives closing and reopening the
store -- proving durability rather than in-process state.
"""

from __future__ import annotations

import uuid

from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.postgres_versions import POSTGRES_STORE_MIGRATIONS
from backend.persistence.migrations.versions import STORE_MIGRATIONS
from backend.persistence.postgres_adapter import PostgresStore
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.tests.persistence_contract.backends import Backend
from backend.tests.persistence_contract.conftest import SqlStore


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _runner(sql_store: SqlStore, conn) -> MigrationRunner:
    if isinstance(sql_store, PostgresStore):
        return MigrationRunner(conn, POSTGRES_STORE_MIGRATIONS, namespace="store", engine="postgres")
    return MigrationRunner(conn, STORE_MIGRATIONS, namespace="store")


def test_rerunning_migrations_is_idempotent(sql_store: SqlStore) -> None:
    session_id = _uid("session")
    sql_store.create_session(session_id=session_id, goal="g", plan=[], artifacts={})

    conn = sql_store.connect()
    _runner(sql_store, conn).run_pending()
    conn.close()

    # Schema and data are both intact -- a second run_pending() touched nothing.
    assert sql_store.get_session(session_id) is not None


def test_down_then_up_round_trip_leaves_a_usable_schema(sql_store: SqlStore) -> None:
    session_id = _uid("session")
    sql_store.create_session(session_id=session_id, goal="g", plan=[], artifacts={})

    conn = sql_store.connect()
    runner = _runner(sql_store, conn)
    runner.run_down(1)
    runner.run_pending()
    conn.close()

    # The store is usable after the round trip: new writes succeed.
    new_session_id = _uid("session")
    sql_store.create_session(session_id=new_session_id, goal="g2", plan=[], artifacts={})
    assert sql_store.get_session(new_session_id) is not None


def test_data_survives_reconnecting_to_the_same_backend(backend: Backend) -> None:
    session_id = _uid("session")

    first: SqlStore
    second: SqlStore
    if backend.is_postgres:
        first = PostgresStore(backend.database_url)
    else:
        first = SQLiteStore(backend.database_url)
    first.create_session(session_id=session_id, goal="durable", plan=[], artifacts={})

    # A brand new store object -- its own connection(s) -- against the same
    # database URL: proves durability, not in-process/connection-local state.
    if backend.is_postgres:
        second = PostgresStore(backend.database_url)
    else:
        second = SQLiteStore(backend.database_url)

    session = second.get_session(session_id)
    assert session is not None
    assert session["goal"] == "durable"
