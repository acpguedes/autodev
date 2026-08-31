"""Connection helpers and the connection-owner typing base shared across submodules."""

from __future__ import annotations

import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Callable, Iterable, Protocol, TypeVar

_DEFAULT_DATABASE_URL = "postgresql://autodev:autodev@postgres:5432/autodev"

_T = TypeVar("_T")


class PostgresPoolExhaustedError(RuntimeError):
    """Raised when the PostgreSQL connection pool cannot hand out a connection in time."""


class PostgresDeadlockError(RuntimeError):
    """Raised when PostgreSQL aborts a transaction as a deadlock victim (SQLSTATE 40P01)."""


class PostgresSerializationFailureError(RuntimeError):
    """Raised when PostgreSQL aborts a transaction for serialization failure (SQLSTATE 40001)."""


_DEADLOCK_DETECTED_SQLSTATE = "40P01"
_SERIALIZATION_FAILURE_SQLSTATE = "40001"

_RETRYABLE_SQLSTATES: dict[str, type[Exception]] = {
    _DEADLOCK_DETECTED_SQLSTATE: PostgresDeadlockError,
    _SERIALIZATION_FAILURE_SQLSTATE: PostgresSerializationFailureError,
}


@dataclass(frozen=True)
class PostgresPoolConfig:
    """Configuration for the process-local PostgreSQL connection pool.

    Attributes:
        min_size: Minimum number of connections the pool keeps open.
        max_size: Maximum number of concurrent checked-out/open connections.
        timeout_seconds: Maximum seconds a caller waits for a connection before
            saturation is reported as :class:`PostgresPoolExhaustedError`.
        statement_timeout_ms: Per-session ``statement_timeout``; ``0`` disables it.
        lock_timeout_ms: Per-session ``lock_timeout``; ``0`` disables it.
        idle_in_transaction_session_timeout_ms: Per-session
            ``idle_in_transaction_session_timeout``; ``0`` disables it.
    """

    min_size: int = 1
    max_size: int = 10
    timeout_seconds: float = 5.0
    statement_timeout_ms: int = 30_000
    lock_timeout_ms: int = 5_000
    idle_in_transaction_session_timeout_ms: int = 60_000

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
        if self.statement_timeout_ms < 0:
            raise ValueError("PostgreSQL statement timeout must be >= 0 ms")
        if self.lock_timeout_ms < 0:
            raise ValueError("PostgreSQL lock timeout must be >= 0 ms")
        if self.idle_in_transaction_session_timeout_ms < 0:
            raise ValueError("PostgreSQL idle-in-transaction timeout must be >= 0 ms")


@dataclass(frozen=True)
class PostgresRetryConfig:
    """Bounded retry configuration for transient, safe-to-retry PostgreSQL errors.

    Attributes:
        max_attempts: Maximum number of times an operation is run (the first
            try plus retries); must be at least 1.
        base_delay_seconds: Base delay for exponential backoff between
            attempts (``base * 2 ** attempt_index``).
    """

    max_attempts: int = 3
    base_delay_seconds: float = 0.05

    def __post_init__(self) -> None:
        """Validate retry bounds at construction time."""
        if self.max_attempts < 1:
            raise ValueError("PostgreSQL retry max attempts must be >= 1")
        if self.base_delay_seconds <= 0:
            raise ValueError("PostgreSQL retry base delay must be > 0 seconds")


class _PostgresPoolSettings(Protocol):
    """Settings fields required to configure the PostgreSQL pool."""

    autodev_postgres_pool_min_size: int
    autodev_postgres_pool_max_size: int
    autodev_postgres_pool_timeout_seconds: float
    autodev_postgres_statement_timeout_ms: int
    autodev_postgres_lock_timeout_ms: int
    autodev_postgres_idle_in_transaction_session_timeout_ms: int


class _PostgresRetrySettings(Protocol):
    """Settings fields required to configure PostgreSQL transient-error retry."""

    autodev_postgres_retry_max_attempts: int
    autodev_postgres_retry_base_delay_seconds: float


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
                configure=self._configure_connection,
                open=True,
            )
        return self._pool

    def _configure_connection(self, conn: Any) -> None:
        """Apply session-level timeout guards to a newly opened pooled connection.

        Called once per physical connection, when the pool creates it --
        before it is ever checked out -- so these ``SET`` statements are
        session-scoped and survive every future checkout/reset cycle without
        being reapplied per transaction (E60-S3-T1).

        Args:
            conn: Freshly opened psycopg connection, not yet handed to a caller.
        """
        conn.execute(f"SET statement_timeout = {int(self.config.statement_timeout_ms)}")
        conn.execute(f"SET lock_timeout = {int(self.config.lock_timeout_ms)}")
        conn.execute(
            "SET idle_in_transaction_session_timeout = "
            f"{int(self.config.idle_in_transaction_session_timeout_ms)}"
        )
        conn.commit()

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
        from backend.observability.metrics import get_metric_sink  # noqa: PLC0415

        pool = self._ensure_pool()
        started_at = time.monotonic()
        try:
            connection_manager = pool.connection(timeout=self.config.timeout_seconds)
            conn = connection_manager.__enter__()
        except Exception as exc:  # noqa: BLE001 - pool implementations raise optional-package classes
            if _is_pool_timeout(exc):
                get_metric_sink().record_postgres_pool_wait(
                    duration_seconds=time.monotonic() - started_at, timed_out=True
                )
                raise PostgresPoolExhaustedError(
                    "PostgreSQL connection pool exhausted; no connection became "
                    f"available within {self.config.timeout_seconds:g}s"
                ) from exc
            raise
        get_metric_sink().record_postgres_pool_wait(
            duration_seconds=time.monotonic() - started_at, timed_out=False
        )
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
        statement_timeout_ms=settings.autodev_postgres_statement_timeout_ms,
        lock_timeout_ms=settings.autodev_postgres_lock_timeout_ms,
        idle_in_transaction_session_timeout_ms=(
            settings.autodev_postgres_idle_in_transaction_session_timeout_ms
        ),
    )


def pool_retry_config_from_settings(settings: _PostgresRetrySettings) -> PostgresRetryConfig:
    """Build a PostgreSQL transient-error retry config from application settings."""
    return PostgresRetryConfig(
        max_attempts=settings.autodev_postgres_retry_max_attempts,
        base_delay_seconds=settings.autodev_postgres_retry_base_delay_seconds,
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


def classify_postgres_error(exc: Exception) -> Exception | None:
    """Classify *exc* as a transient, safe-to-retry PostgreSQL error, if it is one.

    Only serialization failures (``40001``) and deadlock victims (``40P01``)
    are ever retried (E60-S3-T2/T3): both guarantee PostgreSQL has already
    rolled back every effect of the failed attempt before raising, which is
    exactly what makes rerunning the whole operation from scratch safe. Any
    other error -- including ones whose outcome after a partial commit is
    unknown -- is not classified as retryable.

    Args:
        exc: Exception raised by a psycopg operation.

    Returns:
        A typed :class:`PostgresDeadlockError` or
        :class:`PostgresSerializationFailureError` wrapping *exc*, or
        ``None`` if *exc* is not a retryable transient error.
    """
    sqlstate = getattr(getattr(exc, "diag", None), "sqlstate", None)
    error_cls = _RETRYABLE_SQLSTATES.get(str(sqlstate))
    return error_cls(str(exc)) if error_cls is not None else None


def run_with_postgres_retry(
    operation: Callable[[], _T],
    *,
    config: PostgresRetryConfig | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> _T:
    """Run *operation*, retrying it on a classified transient PostgreSQL error.

    *operation* must perform its own connection acquisition, transaction, and
    commit (or rollback) internally, and must be safe to rerun from scratch --
    which holds for any single self-contained transaction, since a
    deadlock/serialization abort undoes every effect of the failed attempt
    (E60-S3-T2). Never wrap an operation whose outcome is unknown after a
    partial failure (e.g. one that has already committed a side effect
    outside the retried transaction).

    Args:
        operation: Zero-argument callable to run, retried in place on
            failure.
        config: Retry bounds; defaults to :class:`PostgresRetryConfig`'s
            defaults.
        sleep: Backoff sleep function, overridable in tests.

    Returns:
        *operation*'s return value from its first successful attempt.

    Raises:
        PostgresDeadlockError: If every attempt is aborted as a deadlock
            victim.
        PostgresSerializationFailureError: If every attempt fails
            serialization.
        Exception: Any non-retryable exception, raised immediately without
            retrying.
    """
    from backend.observability.metrics import get_metric_sink  # noqa: PLC0415

    retry_config = config or PostgresRetryConfig()
    attempt = 0
    while True:
        attempt += 1
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - re-classified or re-raised below
            classified = classify_postgres_error(exc)
            if classified is None:
                raise
            get_metric_sink().record_postgres_transient_error(
                error_type=classified.__class__.__name__
            )
            if attempt >= retry_config.max_attempts:
                raise classified from exc
            sleep(retry_config.base_delay_seconds * (2 ** (attempt - 1)))


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
    "PostgresDeadlockError",
    "PostgresPoolConfig",
    "PostgresPoolExhaustedError",
    "PostgresRetryConfig",
    "PostgresSerializationFailureError",
    "classify_postgres_error",
    "pool_config_from_settings",
    "pool_retry_config_from_settings",
    "reset_postgres_connection",
    "run_with_postgres_retry",
    "_ConnectionOwner",
    "_DEFAULT_DATABASE_URL",
    "_connect",
    "_run_sql",
]
