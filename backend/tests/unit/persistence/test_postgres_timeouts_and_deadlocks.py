"""Real PostgreSQL proof of session timeout guards and deadlock classification (E60-S3).

Mirrors ``backend/tests/unit/quotas/test_postgres_concurrency.py``'s convention:
every test here opens genuine connections against a real PostgreSQL database
and skips automatically unless ``AUTODEV_TEST_POSTGRES_URL`` is set (fails
instead of skipping when ``AUTODEV_REQUIRE_POSTGRES`` is set, i.e. on CI's
PostgreSQL leg). Session-level ``SET`` guards and PostgreSQL's own deadlock
detector cannot be proven against a fake/scripted connection -- they are
properties of the real server.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress

import pytest

from backend.persistence.postgres_adapter import (
    PostgresDeadlockError,
    PostgresRetryConfig,
    classify_postgres_error,
    run_with_postgres_retry,
)
from backend.tests.postgres_gate import REQUIRE_POSTGRES_ENV, require_mark

_POSTGRES_URL = os.environ.get("AUTODEV_TEST_POSTGRES_URL", "")

pytestmark = [
    pytest.mark.slow,
    require_mark(
        bool(_POSTGRES_URL),
        require_env=REQUIRE_POSTGRES_ENV,
        reason="requires AUTODEV_TEST_POSTGRES_URL (a real PostgreSQL, E60)",
    ),
]


def _connect():
    """Open a fresh, non-pooled psycopg connection for direct low-level control."""
    import psycopg  # noqa: PLC0415

    return psycopg.connect(_POSTGRES_URL, autocommit=False)


def _deadlock_table() -> str:
    """Create a fresh two-row scratch table for one test's deadlock recipe."""
    table = f"e60_deadlock_{uuid.uuid4().hex}"
    with _connect() as conn:
        conn.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY)")
        conn.execute(f"INSERT INTO {table} (id) VALUES (1), (2)")
        conn.commit()
    return table


def _lock_rows_in_order(table: str, first_id: int, second_id: int, barrier: threading.Barrier) -> bool:
    """Lock two rows in a given order, synchronized to race against the opposite order.

    Both callers lock *first_id* and then wait at *barrier* before attempting
    *second_id* -- guaranteeing both hold their first lock when they each try
    for the other's, which is exactly the row-lock-ordering conflict
    PostgreSQL's deadlock detector exists to break.
    """
    with _connect() as conn:
        conn.execute(f"SELECT id FROM {table} WHERE id = %s FOR UPDATE", (first_id,))
        barrier.wait(timeout=5)
        conn.execute(f"SELECT id FROM {table} WHERE id = %s FOR UPDATE", (second_id,))
        conn.commit()
    return True


def test_deadlock_is_produced_and_classified_distinctly() -> None:
    """Two transactions locking two rows in opposite order: exactly one is killed as a deadlock (E60-S3-T3)."""
    table = _deadlock_table()
    barrier = threading.Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_lock_rows_in_order, table, 1, 2, barrier)
        future_b = pool.submit(_lock_rows_in_order, table, 2, 1, barrier)

        results: list[bool] = []
        errors: list[Exception] = []
        for future in (future_a, future_b):
            try:
                results.append(future.result(timeout=10))
            except Exception as exc:  # noqa: BLE001 - classifying whatever PostgreSQL raised
                errors.append(exc)

    assert len(results) == 1, "exactly one transaction must win the deadlock"
    assert len(errors) == 1, "exactly one transaction must be killed as the deadlock victim"
    classified = classify_postgres_error(errors[0])
    assert isinstance(classified, PostgresDeadlockError)


def test_deadlock_victim_recovers_via_bounded_retry() -> None:
    """Wrapped in :func:`run_with_postgres_retry`, the deadlock victim's retry succeeds (E60-S3-T2)."""
    table = _deadlock_table()
    barrier = threading.Barrier(2)
    retry_config = PostgresRetryConfig(max_attempts=3, base_delay_seconds=0.05)

    def _attempt(first_id: int, second_id: int) -> bool:
        return run_with_postgres_retry(
            lambda: _lock_rows_in_order(table, first_id, second_id, barrier),
            config=retry_config,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_attempt, 1, 2)
        future_b = pool.submit(_attempt, 2, 1)
        assert future_a.result(timeout=10) is True
        assert future_b.result(timeout=10) is True


def test_statement_timeout_cancels_a_stuck_query() -> None:
    """A ``statement_timeout`` below a query's runtime cancels it with SQLSTATE 57014 (E60-S3-T1)."""
    conn = _connect()
    try:
        conn.execute("SET statement_timeout = 200")
        with pytest.raises(Exception) as excinfo:  # noqa: PT011 - asserting on sqlstate below
            conn.execute("SELECT pg_sleep(2)")
        assert getattr(getattr(excinfo.value, "diag", None), "sqlstate", None) == "57014"
    finally:
        conn.rollback()
        conn.close()


def test_lock_timeout_aborts_a_stuck_lock_wait() -> None:
    """A ``lock_timeout`` below a lock wait's duration aborts it with SQLSTATE 55P03 (E60-S3-T1)."""
    table = _deadlock_table()
    holder = _connect()
    holder.execute(f"SELECT id FROM {table} WHERE id = 1 FOR UPDATE")

    waiter = _connect()
    try:
        waiter.execute("SET lock_timeout = 200")
        with pytest.raises(Exception) as excinfo:  # noqa: PT011
            waiter.execute(f"SELECT id FROM {table} WHERE id = 1 FOR UPDATE")
        assert getattr(getattr(excinfo.value, "diag", None), "sqlstate", None) == "55P03"
    finally:
        waiter.rollback()
        waiter.close()
        holder.rollback()
        holder.close()


def test_idle_in_transaction_session_timeout_terminates_an_abandoned_transaction() -> None:
    """An open transaction left idle past the guard is terminated with SQLSTATE 25P03 (E60-S3-T1)."""
    conn = _connect()
    try:
        conn.execute("SET idle_in_transaction_session_timeout = 200")
        conn.execute("SELECT 1")
        time.sleep(0.5)
        with pytest.raises(Exception) as excinfo:  # noqa: PT011
            conn.execute("SELECT 1")
        assert getattr(getattr(excinfo.value, "diag", None), "sqlstate", None) == "25P03"
    finally:
        with suppress(Exception):  # the session may already be terminated server-side
            conn.close()
