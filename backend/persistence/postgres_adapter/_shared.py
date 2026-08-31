"""Connection helpers and the connection-owner typing base shared across submodules."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Any, Iterable, Protocol

_DEFAULT_DATABASE_URL = "postgresql://autodev:autodev@postgres:5432/autodev"


class PostgresPoolExhaustedError(RuntimeError):
    """Raised when the PostgreSQL connection pool cannot hand out a connection in time."""


@dataclass(frozen=True)
class PostgresPoolConfig:
    """Configuration for the process-local PostgreSQL connection pool.

    Attributes:
        min_size: Minimum number of connections the pool keeps open.
        max_size: Maximum number of concurrent checked-out/open connections.
        timeout_seconds: Maximum seconds a caller waits for a connection before
            saturation is reported as :class:`PostgresPoolExhaustedError`.
    """

    min_size: int = 1
    max_size: int = 10
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        """Validate pool bounds at construction time."""
        if self.min_size < 0:
            raise ValueError("PostgreSQL pool min size must be >= 0")
        if self.max_size < 1:
            raise ValueError("PostgreSQL pool max size must be >= 1")
        if self.min_size > self.max_size:
            raise ValueError("PostgreSQL pool min size cannot exceed max size")
        if self.timeout_seconds <= 0:
            raise ValueError("PostgreSQL pool timeout must be > 0 seconds")


class _PostgresPoolSettings(Protocol):
    """Settings fields required to configure the PostgreSQL pool."""

    autodev_postgres_pool_min_size: int
    autodev_postgres_pool_max_size: int
    autodev_postgres_pool_timeout_seconds: float


class PooledPostgresConnection:
    """Connection-like context manager that resets pooled state on close."""

    def __init__(self, manager: Any, conn: Any) -> None:
        """Wrap a checked-out connection and its pool context manager.

        Args:
            manager: Context manager returned by ``ConnectionPool.connection``.
            conn: Checked-out psycopg connection.
        """
        self._manager = manager
        self._conn = conn
        self._closed = False

    def __enter__(self) -> Any:
        """Return the checked-out connection for ``with store.connect()`` callers."""
        return self._conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Reset tenant state, then return the connection to the pool."""
        return self.close(exc_type, exc, traceback)

    def __getattr__(self, name: str) -> Any:
        """Delegate DB-API operations for legacy raw-connection callers."""
        return getattr(self._conn, name)

    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> bool | None:
        """Reset the connection once and return it to the pool.

        Args:
            exc_type: Optional exception type from context-manager exit.
            exc: Optional exception instance from context-manager exit.
            traceback: Optional traceback from context-manager exit.
        """
        if self._closed:
            return None
        self._closed = True
        manager_result: bool | None = None
        try:
            reset_postgres_connection(self._conn)
        finally:
            manager_result = self._manager.__exit__(exc_type, exc, traceback)
        return manager_result

    def __del__(self) -> None:  # pragma: no cover - defensive fallback for legacy direct callers
        """Return an unclosed borrowed connection to the pool during object cleanup."""
        try:
            self.close()
        except Exception:
            pass


class PostgresConnectionManager:
    """Own a bounded psycopg connection pool behind the store ``connect()`` contract."""

    def __init__(self, database_url: str, config: PostgresPoolConfig | None = None) -> None:
        """Create a manager for *database_url* without opening the pool yet.

        Args:
            database_url: PostgreSQL connection URL.
            config: Pool sizing and bounded-wait configuration.
        """
        self.database_url = database_url
        self.config = config or PostgresPoolConfig()
        self._pool: Any | None = None

    def _ensure_pool(self) -> Any:
        """Return the lazily-created psycopg pool.

        Raises:
            RuntimeError: If the ``psycopg_pool`` package is not installed.
        """
        if self._pool is None:
            try:
                from psycopg_pool import ConnectionPool  # type: ignore[import-untyped]
            except ImportError as exc:  # pragma: no cover - exercised when optional dep missing
                raise RuntimeError(
                    "psycopg_pool is required for PostgreSQL persistence. "
                    "Install backend requirements with the psycopg pool extra."
                ) from exc
            self._pool = ConnectionPool(
                self.database_url,
                min_size=self.config.min_size,
                max_size=self.config.max_size,
                timeout=self.config.timeout_seconds,
                open=True,
            )
        return self._pool

    def connect(self) -> PooledPostgresConnection:
        """Borrow one connection from the pool using a bounded wait.

        Returns:
            A connection-like object that can be used directly by legacy callers
            or as a context manager by newer call sites. Closing or exiting it
            resets tenant session state before returning the connection to the
            pool.

        Raises:
            PostgresPoolExhaustedError: If the pool cannot satisfy the request
                within the configured timeout.
        """
        pool = self._ensure_pool()
        try:
            connection_manager = pool.connection(timeout=self.config.timeout_seconds)
            conn = connection_manager.__enter__()
        except Exception as exc:  # noqa: BLE001 - pool implementations raise optional-package classes
            if _is_pool_timeout(exc):
                raise PostgresPoolExhaustedError(
                    "PostgreSQL connection pool exhausted; no connection became "
                    f"available within {self.config.timeout_seconds:g}s"
                ) from exc
            raise
        return PooledPostgresConnection(connection_manager, conn)

    def close(self) -> None:
        """Close the pool and all idle connections; in-flight borrowers drain by the pool contract."""
        pool = self._pool
        self._pool = None
        if pool is not None:
            pool.close()

    def stats(self) -> dict[str, int]:
        """Return the pool's current statistics when available.

        Returns:
            A mapping of integer pool counters. Missing/unsupported stats return
            an empty mapping so readiness and metrics can degrade safely.
        """
        pool = self._pool
        if pool is None or not hasattr(pool, "get_stats"):
            return {}
        raw_stats = pool.get_stats()
        return {str(key): int(value) for key, value in dict(raw_stats).items()}


def pool_config_from_settings(settings: _PostgresPoolSettings) -> PostgresPoolConfig:
    """Build a PostgreSQL pool config from application settings."""
    return PostgresPoolConfig(
        min_size=settings.autodev_postgres_pool_min_size,
        max_size=settings.autodev_postgres_pool_max_size,
        timeout_seconds=settings.autodev_postgres_pool_timeout_seconds,
    )


def reset_postgres_connection(conn: Any) -> None:
    """Return a pooled PostgreSQL connection to a tenant-neutral clean state.

    The tenant GUC is set transaction-locally by
    :func:`backend.persistence.tenancy.set_postgres_tenant`, so a rollback is
    sufficient to clear normal RLS scope. ``RESET app.tenant_id`` additionally
    clears any accidental session-level assignment before the connection is
    reused by another request.

    Args:
        conn: psycopg connection being returned to the pool.
    """
    try:
        conn.rollback()
    finally:
        conn.execute("RESET app.tenant_id")
        conn.commit()


def _is_pool_timeout(exc: Exception) -> bool:
    """Return whether *exc* looks like a psycopg-pool acquisition timeout."""
    return exc.__class__.__name__ in {"PoolTimeout", "TooManyRequests"}


def _connect(database_url: str) -> Any:
    """Open a new psycopg connection to the given PostgreSQL URL.

    Kept as the explicit non-pooled primitive for preflight, migrations, and
    tests that need to bypass the process pool.

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        A new database connection.

    Raises:
        RuntimeError: If the ``psycopg`` package is not installed.
    """
    try:
        import psycopg  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError(
            "psycopg is required for PostgreSQL persistence. Install backend requirements."
        ) from exc
    return psycopg.connect(database_url)


def _run_sql(conn: Any, statements: Iterable[str]) -> None:
    """Execute and commit a sequence of SQL statements on one connection."""
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()


class _ConnectionOwner:
    """Typing base for ``PostgresStore``'s mixins: declares the ``connect()`` every mixin calls.

    ``PostgresStore`` (in :mod:`store`) provides the real implementation;
    this placeholder exists only so each mixin can be read, and type-checked,
    on its own without depending on the composed class.
    """

    database_url: str

    def connect(self) -> Any:  # pragma: no cover - overridden by PostgresStore
        raise NotImplementedError


__all__ = [
    "PostgresConnectionManager",
    "PostgresPoolConfig",
    "PostgresPoolExhaustedError",
    "pool_config_from_settings",
    "reset_postgres_connection",
    "_ConnectionOwner",
    "_DEFAULT_DATABASE_URL",
    "_connect",
    "_run_sql",
]
