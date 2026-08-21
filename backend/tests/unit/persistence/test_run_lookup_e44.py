"""Direct run/turn lookup cost regression tests (E44-S1).

``GET /v2/turns/{turn_id}`` used to scan every session's runs to resolve one
run id. These tests pin the replacement contract — ``RunRepository.get_run``
— on both adapters: it must cost at most two SQL statements on a single
connection regardless of how many sessions or runs exist, and it must never
surface another tenant's run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.persistence.postgres_adapter import PostgresStore
from backend.persistence.sqlite_adapter import SQLiteStore

from backend.tests.unit.persistence.e44_helpers import StatementCounter, data_statements
from backend.tests.unit.persistence.test_postgres_adapter import ScriptedConnection


def _seed(
    target: SQLiteStore, *, sessions: int, runs_per_session: int, tenant_id: str
) -> str:
    """Seed *sessions* sessions with *runs_per_session* runs each.

    Args:
        target: Store to seed.
        sessions: Number of sessions to create.
        runs_per_session: Number of runs to create per session.
        tenant_id: Tenant every seeded row belongs to.

    Returns:
        The run id of the last run created, for use as a lookup target.
    """
    run_id = ""
    for s in range(sessions):
        session_id = f"{tenant_id}-s{s}"
        target.create_session(
            session_id=session_id, goal="g", plan=["p"], artifacts={}, tenant_id=tenant_id
        )
        for r in range(runs_per_session):
            run_id = f"{tenant_id}-s{s}-r{r}"
            target.create_run(
                run_id=run_id,
                session_id=session_id,
                status="completed",
                run_type="auto",
                current_state="done",
                trigger_message="go",
                results=[{"agent": "coder", "content": "c", "metadata": {}}],
                steps=[
                    {
                        "step_key": f"k{i}",
                        "agent": "coder",
                        "status": "completed",
                        "started_at": "t0",
                        "completed_at": "t1",
                        "attempt": 1,
                    }
                    for i in range(3)
                ],
                tenant_id=tenant_id,
            )
    return run_id


@pytest.fixture
def sqlite_store(tmp_path: Path) -> SQLiteStore:
    """Build a :class:`SQLiteStore` backed by a temporary database file."""
    return SQLiteStore(database_url=f"sqlite:///{tmp_path / 'e44.db'}")


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def test_sqlite_get_run_returns_same_record_as_list_runs(sqlite_store: SQLiteStore) -> None:
    """get_run returns the record list_runs would return for the same run."""
    run_id = _seed(sqlite_store, sessions=2, runs_per_session=2, tenant_id="default")
    from_list = [
        run for run in sqlite_store.list_runs("default-s1") if run["id"] == run_id
    ][0]
    assert sqlite_store.get_run(run_id) == from_list


def test_sqlite_get_run_returns_none_for_unknown_id(sqlite_store: SQLiteStore) -> None:
    """An unknown run id resolves to None rather than raising."""
    _seed(sqlite_store, sessions=1, runs_per_session=1, tenant_id="default")
    assert sqlite_store.get_run("no-such-run") is None


def test_sqlite_get_run_does_not_cross_tenants(sqlite_store: SQLiteStore) -> None:
    """A run belonging to another tenant is indistinguishable from a missing one."""
    run_id = _seed(sqlite_store, sessions=1, runs_per_session=1, tenant_id="tenant-a")
    assert sqlite_store.get_run(run_id, tenant_id="tenant-a") is not None
    assert sqlite_store.get_run(run_id, tenant_id="tenant-b") is None


@pytest.mark.parametrize("sessions", [1, 20])
def test_sqlite_get_run_costs_two_statements_on_one_connection(
    sqlite_store: SQLiteStore, sessions: int
) -> None:
    """Lookup cost stays at 2 statements / 1 connection as the store grows."""
    run_id = _seed(sqlite_store, sessions=sessions, runs_per_session=5, tenant_id="default")
    counter = StatementCounter()
    counter.install(sqlite_store)

    assert sqlite_store.get_run(run_id) is not None

    assert len(counter.statements) <= 2, counter.statements
    assert counter.connections == 1


def test_sqlite_get_run_missing_run_skips_the_step_query(sqlite_store: SQLiteStore) -> None:
    """A miss short-circuits after the primary-key lookup — no step query."""
    _seed(sqlite_store, sessions=1, runs_per_session=1, tenant_id="default")
    counter = StatementCounter()
    counter.install(sqlite_store)

    assert sqlite_store.get_run("nope") is None

    assert len(counter.statements) == 1


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------


def test_postgres_get_run_costs_two_statements(
    pg_store: PostgresStore, pg_conn: ScriptedConnection
) -> None:
    """get_run issues exactly the run lookup plus one batched step query."""
    pg_conn.fetchone_queue.append(
        ("r1", "s1", "running", "auto", "planning", "go", "[]", "2024-01-01", "2024-01-02")
    )
    pg_conn.fetchall_queue.append([("r1", "k1", "a1", "done", "t0", "t1", 1)])

    result = pg_store.get_run("r1")

    assert result is not None
    assert result["id"] == "r1"
    assert result["steps"] == [
        {
            "step_key": "k1",
            "agent": "a1",
            "status": "done",
            "started_at": "t0",
            "completed_at": "t1",
            "attempt": 1,
        }
    ]
    statements = data_statements(pg_conn)
    assert len(statements) == 2, statements
    assert "FROM runs WHERE id = %s" in statements[0]
    assert "FROM run_steps" in statements[1]


def test_postgres_get_run_missing_returns_none_without_step_query(
    pg_store: PostgresStore, pg_conn: ScriptedConnection
) -> None:
    """A missing run short-circuits before the step query runs."""
    pg_conn.fetchone_queue.append(None)

    assert pg_store.get_run("missing") is None
    assert len(data_statements(pg_conn)) == 1


def test_postgres_get_run_scopes_the_connection_to_the_tenant(
    pg_store: PostgresStore, pg_conn: ScriptedConnection
) -> None:
    """RLS is armed for the caller's tenant before the run is read."""
    pg_conn.fetchone_queue.append(None)

    pg_store.get_run("r1", tenant_id="tenant-a")

    first_sql, first_params = pg_conn.executed[0]
    assert "set_config" in first_sql
    assert first_params == ("tenant-a",)


def test_postgres_list_runs_uses_one_batched_step_query(
    pg_store: PostgresStore, pg_conn: ScriptedConnection
) -> None:
    """list_runs costs 2 statements for N runs, not 1 + N (E44-S1/S2)."""
    pg_conn.fetchall_queue.append(
        [
            (f"r{i}", "s1", "running", "auto", "planning", "go", "[]", "2024-01-01", "2024-01-02")
            for i in range(5)
        ]
    )
    pg_conn.fetchall_queue.append(
        [(f"r{i}", "k1", "a1", "done", "t0", "t1", 1) for i in range(5)]
    )

    result = pg_store.list_runs("s1")

    assert len(result) == 5
    assert all(run["steps"] for run in result)
    assert len(data_statements(pg_conn)) == 2


@pytest.mark.parametrize("run_count", [1, 100])
def test_sqlite_list_runs_uses_one_batched_step_query(
    sqlite_store: SQLiteStore, run_count: int
) -> None:
    """SQLite list_runs costs 2 statements / 1 connection for N runs, not 1 + N."""
    _seed(sqlite_store, sessions=1, runs_per_session=run_count, tenant_id="default")
    counter = StatementCounter()
    counter.install(sqlite_store)

    runs = sqlite_store.list_runs("default-s0")

    assert len(runs) == run_count
    assert all(len(run["steps"]) == 3 for run in runs)
    assert len(counter.statements) == 2, counter.statements
    assert counter.connections == 1


def test_sqlite_update_run_uses_a_single_connection(sqlite_store: SQLiteStore) -> None:
    """Persisting a run and its steps opens one connection, not one per row (E44-S2)."""
    _seed(sqlite_store, sessions=1, runs_per_session=1, tenant_id="default")
    counter = StatementCounter()
    counter.install(sqlite_store)

    sqlite_store.update_run(
        run_id="default-s0-r0",
        status="completed",
        current_state="done",
        results=[],
        steps=[
            {
                "step_key": f"k{i}",
                "agent": "coder",
                "status": "completed",
                "started_at": "t0",
                "completed_at": "t1",
                "attempt": 1,
            }
            for i in range(25)
        ],
    )

    assert counter.connections == 1
