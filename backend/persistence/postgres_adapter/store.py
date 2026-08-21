"""Postgres-backed store composing every persistence-protocol mixin (E47-S4)."""

from __future__ import annotations

from typing import Any

from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.postgres_versions import POSTGRES_STORE_MIGRATIONS
from backend.persistence.postgres_adapter._shared import (
    _DEFAULT_DATABASE_URL,
    _connect,
)
from backend.persistence.postgres_adapter.eval_scoring import _EvalScoringMixin
from backend.persistence.postgres_adapter.messages import _MessagesMixin
from backend.persistence.postgres_adapter.runs import _RunsMixin
from backend.persistence.postgres_adapter.sessions import _SessionsMixin


class PostgresStore(_SessionsMixin, _RunsMixin, _MessagesMixin, _EvalScoringMixin):
    """Postgres-backed store implementing sessions, runs, and messages.

    Split by data domain across this package's modules (E47-S4): see
    ``sessions.py``, ``runs.py``, ``messages.py``, ``eval_scoring.py``. Each
    mixin is independently readable and type-checkable against
    ``_ConnectionOwner``; only this class provides the real ``connect()``.
    """

    def __init__(self, database_url: str = _DEFAULT_DATABASE_URL) -> None:
        """Initialize the store and apply its migrations.

        Args:
            database_url: PostgreSQL connection URL.
        """
        self.database_url = database_url
        with self.connect() as conn:
            self._run_migrations(conn)

    def connect(self) -> Any:
        """Open a new connection to this store's database."""
        return _connect(self.database_url)

    def _run_migrations(self, conn: Any) -> None:
        """Apply this store's versioned migrations via the shared runner.

        Uses the same :class:`MigrationRunner` machinery as
        :class:`~backend.persistence.sqlite_adapter.store.SQLiteStore`, running
        against a psycopg connection (``engine="postgres"``) instead of ad
        hoc ``CREATE TABLE IF NOT EXISTS`` statements. See
        ``backend/persistence/migrations/postgres_versions.py`` for the
        migration list.
        """
        MigrationRunner(
            conn, POSTGRES_STORE_MIGRATIONS, namespace="store", engine="postgres"
        ).run_pending()


__all__ = ["PostgresStore"]
