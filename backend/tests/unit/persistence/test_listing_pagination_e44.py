"""Database-level listing pagination regression tests (E44-S3).

``/v2/sessions`` and the runs/turns listings used to load every row and slice
in memory, and each session summary replayed that session's whole message
history. These tests pin the replacement contract: a page costs a fixed
number of statements regardless of how much data the tenant has, and its
contents match what the old load-everything-then-slice path produced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.persistence.postgres_adapter import PostgresStore
from backend.persistence.sqlite_adapter import SQLiteStore

from backend.tests.unit.persistence.e44_helpers import StatementCounter, data_statements
from backend.tests.unit.persistence.test_postgres_adapter import ScriptedConnection


@pytest.fixture
def sqlite_store(tmp_path: Path) -> SQLiteStore:
    """Build a :class:`SQLiteStore` backed by a temporary database file."""
    return SQLiteStore(database_url=f"sqlite:///{tmp_path / 'e44-s3.db'}")


def _seed_sessions(
    target: SQLiteStore,
    *,
    count: int,
    messages_each: int,
    tenant_id: str = "default",
    prefix: str = "s",
) -> None:
    """Create *count* sessions, each with *messages_each* messages.

    Args:
        target: Store to seed.
        count: Number of sessions to create.
        messages_each: Number of messages to append to every session.
        tenant_id: Tenant every seeded row belongs to.
        prefix: Session-id prefix, so seeds for different tenants do not
            collide on the ``sessions`` primary key.
    """
    for index in range(count):
        session_id = f"{prefix}{index:03d}"
        target.create_session(
            session_id=session_id, goal=f"goal {index}", plan=[], artifacts={}, tenant_id=tenant_id
        )
        if messages_each:
            target.append_messages(
                session_id,
                f"r{index}",
                [{"role": "user", "content": f"m{i}"} for i in range(messages_each)],
                tenant_id=tenant_id,
            )


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def test_sqlite_session_page_matches_in_memory_slice(sqlite_store: SQLiteStore) -> None:
    """SQL windowing yields the same rows, in the same order, as slicing would."""
    _seed_sessions(sqlite_store, count=7, messages_each=0)
    everything = sqlite_store.list_sessions()

    page, total = sqlite_store.list_sessions_page(limit=3, offset=2)

    assert total == 7
    assert [record["id"] for record in page] == [
        record["id"] for record in everything[2:5]
    ]


def test_sqlite_session_page_reports_message_activity(sqlite_store: SQLiteStore) -> None:
    """Each page record carries its message count and last activity timestamp."""
    _seed_sessions(sqlite_store, count=2, messages_each=4)
    sqlite_store.create_session(
        session_id="s999", goal="quiet", plan=[], artifacts={}, tenant_id="default"
    )

    page, _ = sqlite_store.list_sessions_page(limit=10, offset=0)
    by_id = {record["id"]: record for record in page}

    assert by_id["s000"]["message_count"] == 4
    assert by_id["s000"]["last_activity"] is not None
    assert by_id["s999"]["message_count"] == 0
    assert by_id["s999"]["last_activity"] is None


def test_sqlite_session_page_excludes_other_tenants(sqlite_store: SQLiteStore) -> None:
    """A tenant's page never counts or returns another tenant's sessions."""
    _seed_sessions(sqlite_store, count=3, messages_each=1, tenant_id="tenant-a", prefix="a")
    _seed_sessions(sqlite_store, count=2, messages_each=1, tenant_id="tenant-b", prefix="b")

    page, total = sqlite_store.list_sessions_page(limit=50, offset=0, tenant_id="tenant-b")

    assert total == 2
    assert len(page) == 2


@pytest.mark.parametrize("session_count", [5, 200])
def test_sqlite_session_page_cost_is_independent_of_store_size(
    sqlite_store: SQLiteStore, session_count: int
) -> None:
    """A page costs 3 statements / 1 connection whatever the tenant's size."""
    _seed_sessions(sqlite_store, count=session_count, messages_each=3)
    counter = StatementCounter()
    counter.install(sqlite_store)

    page, total = sqlite_store.list_sessions_page(limit=20, offset=0)

    assert total == session_count
    assert len(page) == min(20, session_count)
    assert len(counter.statements) == 3, counter.statements
    assert counter.connections == 1


def test_sqlite_run_page_matches_in_memory_slice(sqlite_store: SQLiteStore) -> None:
    """Run pages preserve list_runs' ordering and contents exactly."""
    sqlite_store.create_session(
        session_id="s1", goal="g", plan=[], artifacts={}, tenant_id="default"
    )
    for index in range(6):
        sqlite_store.create_run(
            run_id=f"r{index}",
            session_id="s1",
            status="completed",
            run_type="auto",
            current_state="done",
            trigger_message="go",
            results=[],
            steps=[
                {
                    "step_key": "k0",
                    "agent": "coder",
                    "status": "completed",
                    "started_at": "t0",
                    "completed_at": "t1",
                    "attempt": 1,
                }
            ],
            tenant_id="default",
        )
    everything = sqlite_store.list_runs("s1")

    page, total = sqlite_store.list_runs_page("s1", limit=2, offset=3)

    assert total == 6
    assert page == everything[3:5]


def test_sqlite_run_page_cost_is_independent_of_run_count(sqlite_store: SQLiteStore) -> None:
    """A run page costs 3 statements / 1 connection for any number of runs."""
    sqlite_store.create_session(
        session_id="s1", goal="g", plan=[], artifacts={}, tenant_id="default"
    )
    for index in range(60):
        sqlite_store.create_run(
            run_id=f"r{index}",
            session_id="s1",
            status="completed",
            run_type="auto",
            current_state="done",
            trigger_message="go",
            results=[],
            steps=[],
            tenant_id="default",
        )
    counter = StatementCounter()
    counter.install(sqlite_store)

    page, total = sqlite_store.list_runs_page("s1", limit=10, offset=0)

    assert total == 60
    assert len(page) == 10
    assert len(counter.statements) == 3, counter.statements
    assert counter.connections == 1


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------


def test_postgres_session_page_costs_three_statements(
    pg_store: PostgresStore, pg_conn: ScriptedConnection
) -> None:
    """COUNT, the windowed page, and one message aggregate — nothing per session."""
    pg_conn.fetchone_queue.append((42,))
    pg_conn.fetchall_queue.append(
        [
            (f"s{i}", f"goal {i}", "[]", "{}", "2024-01-01", "2024-01-02")
            for i in range(3)
        ]
    )
    pg_conn.fetchall_queue.append([("s0", 2, "2024-01-03")])

    page, total = pg_store.list_sessions_page(limit=3, offset=0)

    assert total == 42
    assert [record["id"] for record in page] == ["s0", "s1", "s2"]
    assert page[0]["message_count"] == 2
    assert page[0]["last_activity"] == "2024-01-03"
    assert page[1]["message_count"] == 0
    assert page[1]["last_activity"] is None
    statements = data_statements(pg_conn)
    assert len(statements) == 3, statements
    assert "COUNT(*) FROM sessions" in statements[0]
    assert "LIMIT %s OFFSET %s" in statements[1]
    assert "GROUP BY session_id" in statements[2]


def test_postgres_session_page_skips_the_aggregate_when_empty(
    pg_store: PostgresStore, pg_conn: ScriptedConnection
) -> None:
    """An empty page issues no message aggregate at all."""
    pg_conn.fetchone_queue.append((0,))
    pg_conn.fetchall_queue.append([])

    page, total = pg_store.list_sessions_page(limit=10, offset=0)

    assert (page, total) == ([], 0)
    assert len(data_statements(pg_conn)) == 2


def test_postgres_run_page_costs_three_statements(
    pg_store: PostgresStore, pg_conn: ScriptedConnection
) -> None:
    """COUNT, the windowed page, and one batched step query."""
    pg_conn.fetchone_queue.append((9,))
    pg_conn.fetchall_queue.append(
        [
            (f"r{i}", "s1", "completed", "auto", "done", "go", "[]", "2024-01-01", "2024-01-02")
            for i in range(2)
        ]
    )
    pg_conn.fetchall_queue.append([("r0", "k1", "a1", "done", "t0", "t1", 1)])

    page, total = pg_store.list_runs_page("s1", limit=2, offset=4)

    assert total == 9
    assert [run["id"] for run in page] == ["r0", "r1"]
    assert page[0]["steps"] and page[1]["steps"] == []
    statements = data_statements(pg_conn)
    assert len(statements) == 3, statements
    assert "COUNT(*) FROM runs" in statements[0]
    assert "LIMIT %s OFFSET %s" in statements[1]
    assert "FROM run_steps" in statements[2]
