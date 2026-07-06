"""Versioned migration runner for SQL-based stores (SQLite and PostgreSQL)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence, Union


MigrationFn = Callable[[Any], None]

#: Connections accepted by :class:`MigrationRunner`: a ``sqlite3.Connection``
#: for SQLite stores, or a psycopg connection (or connection-like object
#: exposing ``execute``/``commit``) for PostgreSQL stores.
Engine = Literal["sqlite", "postgres"]


def _noop_down(conn: Any) -> None:  # noqa: ARG001 - intentional no-op signature parity
    """Documented no-op down migration.

    Used as the default ``down`` for migrations that predate down-migration
    support (see :class:`Migration`) or for forward steps where a true
    rollback is not meaningful (e.g. best-effort backfills). Additive,
    non-destructive forward migrations are safe to leave with a no-op down —
    rolling back only rewinds the recorded schema version, it does not undo
    the (harmless) DDL.

    Args:
        conn: Open database connection; unused.
    """
    return None


@dataclass(frozen=True)
class Migration:
    """A single versioned schema migration with a forward step and a rollback step.

    Attributes:
        up: Callable applying the migration's forward DDL/DML.
        down: Callable reverting the migration. Defaults to :func:`_noop_down`
            for migrations where a true rollback is not meaningful or predates
            down-migration support.
        name: Human-readable identifier for logging/debugging; defaults to
            ``up.__name__`` when constructed via :class:`MigrationRunner`.
    """

    up: MigrationFn
    down: MigrationFn = _noop_down
    name: str = ""


#: Either a full :class:`Migration` (with an explicit down step) or a bare
#: forward-only callable, for backward compatibility with migration lists
#: written before down-migration support existed.
MigrationEntry = Union[Migration, MigrationFn]


def _as_migration(entry: MigrationEntry) -> Migration:
    """Normalize a migration list entry to a :class:`Migration`.

    Args:
        entry: Either a :class:`Migration` or a bare forward-only callable.

    Returns:
        The entry unchanged if already a :class:`Migration`; otherwise a new
        :class:`Migration` wrapping the callable as ``up`` with a
        :func:`_noop_down` rollback.
    """
    if isinstance(entry, Migration):
        return entry
    return Migration(up=entry, down=_noop_down, name=getattr(entry, "__name__", ""))


class MigrationRunner:
    """Apply and roll back pending migrations on a connection, in version order.

    Usage::

        with sqlite3.connect(path) as conn:
            MigrationRunner(conn, MIGRATIONS, namespace="store").run_pending()

    The ``schema_version`` table stores (namespace, version) rows so multiple
    stores that share one database each track their own migration version
    independently. Each migration's ``up``/``down`` callable receives the open
    connection; the runner commits after every successfully applied step.

    Set ``engine="postgres"`` when running against a psycopg connection —
    this skips the SQLite-only legacy single-column ``schema_version``
    detection, which does not apply to PostgreSQL stores (they have always
    used the ``(namespace, version)`` shape).
    """

    def __init__(
        self,
        conn: Any,
        migrations: Sequence[MigrationEntry],
        namespace: str = "default",
        engine: Engine = "sqlite",
    ) -> None:
        """Initialize the runner.

        Args:
            conn: Open database connection (SQLite or PostgreSQL, per *engine*).
            migrations: Ordered list of migrations; each is either a
                :class:`Migration` or a bare forward-only callable.
            namespace: ``schema_version`` row key for this store, allowing
                multiple stores to share one database.
            engine: ``"sqlite"`` (default, preserves prior behavior) or
                ``"postgres"``.
        """
        self._conn = conn
        self._migrations = [_as_migration(entry) for entry in migrations]
        self._namespace = namespace
        self._engine = engine
        self._param = "?" if engine == "sqlite" else "%s"

    def _ensure_version_table(self) -> None:
        """Create the ``schema_version`` table, migrating the legacy SQLite shape if found."""
        if self._engine == "sqlite":
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
        else:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(namespace TEXT NOT NULL PRIMARY KEY, version INTEGER NOT NULL)"
            )
        self._conn.commit()

    def _current_version(self) -> int:
        """Return the schema version currently recorded for this runner's namespace."""
        row = self._conn.execute(
            f"SELECT version FROM schema_version WHERE namespace = {self._param}",
            (self._namespace,),
        ).fetchone()
        return row[0] if row else 0

    def _set_version(self, version: int) -> None:
        """Record *version* as the current schema version for this runner's namespace."""
        self._conn.execute(
            f"INSERT INTO schema_version (namespace, version) VALUES ({self._param}, {self._param})"
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
                migration.up(self._conn)
                self._set_version(idx)

    def rollback_to(self, version: int) -> None:
        """Roll back to a specific target schema version.

        Runs each migration's ``down`` callable in reverse order, from the
        current version down to (but not including) *version*.

        Args:
            version: Target schema version to roll back to.

        Raises:
            ValueError: If *version* is negative or greater than the current version.
        """
        self._ensure_version_table()
        current = self._current_version()
        if version < 0 or version > current:
            raise ValueError(
                f"invalid rollback target {version!r} (current version is {current})"
            )
        for idx in range(current, version, -1):
            migration = self._migrations[idx - 1]
            migration.down(self._conn)
            self._set_version(idx - 1)

    def run_down(self, steps: int = 1) -> None:
        """Roll back the *steps* most recently applied migrations.

        Args:
            steps: Number of migrations to roll back from the current version.

        Raises:
            ValueError: If *steps* is negative or exceeds the current version.
        """
        if steps < 0:
            raise ValueError("steps must be non-negative")
        self._ensure_version_table()
        current = self._current_version()
        self.rollback_to(current - steps)


__all__ = ["Engine", "Migration", "MigrationEntry", "MigrationFn", "MigrationRunner"]
