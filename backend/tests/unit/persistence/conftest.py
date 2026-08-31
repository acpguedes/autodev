"""Shared fixtures for the persistence adapter tests.

The Postgres fixtures here wrap ``test_postgres_adapter``'s scripted psycopg
fake so several test modules can drive a ``PostgresStore`` without importing
each other's fixtures (which would shadow their own parameter names).
"""

from __future__ import annotations

import pytest

from backend.persistence.postgres_adapter import PostgresStore

from backend.tests.unit.persistence.test_postgres_adapter import (
    ScriptedConnection,
    install_scripted_psycopg,
)


@pytest.fixture
def pg_conn(monkeypatch: pytest.MonkeyPatch) -> ScriptedConnection:
    """Install the scripted psycopg fake and return its shared connection."""
    return install_scripted_psycopg(monkeypatch)


@pytest.fixture
def pg_store(monkeypatch: pytest.MonkeyPatch, pg_conn: ScriptedConnection) -> PostgresStore:
    """Build a ``PostgresStore`` against the scripted connection, skipping migrations
    and vector-extension provisioning (E48-S2) so scripted fetch queues stay reserved
    for the CRUD statements under test."""
    monkeypatch.setattr(PostgresStore, "_run_migrations", lambda self, conn: None)
    monkeypatch.setattr(
        "backend.persistence.postgres_adapter.store.provision_vector_extension",
        lambda conn: None,
    )
    store = PostgresStore(database_url="postgresql://test/db")
    # Constructing the store checks out one connection, which the pool
    # configures with its one-time session timeout guards (E60-S3-T1) --
    # clear that pool-plumbing so every test's own statement-cost
    # assertions start from a clean slate.
    pg_conn.executed.clear()
    return store
