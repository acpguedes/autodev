"""Versioned migration runner for SQLite stores."""

from __future__ import annotations

import sqlite3
from typing import Callable, Sequence


Migration = Callable[[sqlite3.Connection], None]


class MigrationRunner:
    """Apply pending migrations to a SQLite connection in version order.

    Usage::

        with sqlite3.connect(path) as conn:
            MigrationRunner(conn, MIGRATIONS, namespace="store").run_pending()

    The ``schema_version`` table stores (namespace, version) rows so multiple
    stores that share one SQLite file each track their own migration version
    independently.  Each migration callable receives the open connection; the
    runner commits after every successful migration.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        migrations: Sequence[Migration],
        namespace: str = "default",
    ) -> None:
        self._conn = conn
        self._migrations = migrations
        self._namespace = namespace

    def _ensure_version_table(self) -> None:
        # Check if old single-column schema_version table exists and migrate it.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(schema_version)").fetchall()
        }
        if cols and "namespace" not in cols:
            # Old schema: (version INTEGER). Read value then recreate.
            old_row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            old_version = old_row[0] if old_row else 0
            self._conn.execute("DROP TABLE schema_version")
            self._conn.execute(
                "CREATE TABLE schema_version "
                "(namespace TEXT NOT NULL PRIMARY KEY, version INTEGER NOT NULL)"
            )
            if old_version:
                self._conn.execute(
                    "INSERT INTO schema_version (namespace, version) VALUES (?, ?)",
                    ("store", old_version),
                )
        else:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(namespace TEXT NOT NULL PRIMARY KEY, version INTEGER NOT NULL)"
            )
        self._conn.commit()

    def _current_version(self) -> int:
        row = self._conn.execute(
            "SELECT version FROM schema_version WHERE namespace = ?",
            (self._namespace,),
        ).fetchone()
        return row[0] if row else 0

    def _set_version(self, version: int) -> None:
        self._conn.execute(
            "INSERT INTO schema_version (namespace, version) VALUES (?, ?)"
            " ON CONFLICT(namespace) DO UPDATE SET version = excluded.version",
            (self._namespace, version),
        )
        self._conn.commit()

    def run_pending(self) -> None:
        """Run all migrations whose 1-based index exceeds the current version."""
        self._ensure_version_table()
        current = self._current_version()
        for idx, migration in enumerate(self._migrations, start=1):
            if idx > current:
                migration(self._conn)
                self._set_version(idx)
