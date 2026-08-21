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
    """Build a ``PostgresStore`` against the scripted connection, skipping migrations."""
    monkeypatch.setattr(PostgresStore, "_run_migrations", lambda self, conn: None)
    return PostgresStore(database_url="postgresql://test/db")
