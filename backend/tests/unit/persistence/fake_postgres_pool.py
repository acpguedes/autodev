"""Fake psycopg/psycopg_pool modules for PostgreSQL adapter unit tests."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Callable, Iterator, TypeVar

import pytest

_ConnT = TypeVar("_ConnT")


class PoolTimeout(Exception):
    """Fake psycopg_pool timeout exception, matched by class name."""


class FakeConnectionPool:
    """Small fake of ``psycopg_pool.ConnectionPool`` for unit tests."""

    instances: list["FakeConnectionPool"] = []

    def __init__(
        self,
        conninfo: str,
        *,
        min_size: int,
        max_size: int,
        timeout: float,
        open: bool,
    ) -> None:
        """Record pool construction args and create one reusable connection."""
        assert conninfo.startswith("postgresql://")
        self.conninfo = conninfo
        self.min_size = min_size
        self.max_size = max_size
        self.timeout = timeout
        self.open = open
        self.connection_calls: list[float | None] = []
        self.closed = False
        self.conn: Any = None
        FakeConnectionPool.instances.append(self)

    @contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[Any]:
        """Yield the reusable fake connection unless the pool cap is already reached."""
        self.connection_calls.append(timeout)
        if getattr(self.conn, "active_checkouts", 0) >= self.max_size:
            raise PoolTimeout("pool exhausted")
        with self.conn:
            yield self.conn

    def close(self) -> None:
        """Mark the fake pool and connection closed."""
        self.closed = True
        if self.conn is not None:
            self.conn.closed = True

    def get_stats(self) -> dict[str, int]:
        """Return simple fake pool stats."""
        active = int(getattr(self.conn, "active_checkouts", 0) if self.conn is not None else 0)
        return {
            "pool_min": self.min_size,
            "pool_max": self.max_size,
            "pool_available": self.max_size - active,
            "requests_waiting": 0,
        }


def install_fake_postgres_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connection_factory: Callable[[], _ConnT],
) -> list[_ConnT]:
    """Install fake ``psycopg`` and ``psycopg_pool`` modules.

    Args:
        monkeypatch: Active pytest monkeypatch fixture.
        connection_factory: Factory returning the connection fake for each raw
            ``psycopg.connect`` call and each pool instance.

    Returns:
        Connections created through either fake module, in creation order.
    """
    connections: list[_ConnT] = []
    FakeConnectionPool.instances.clear()

    def new_connection() -> _ConnT:
        conn = connection_factory()
        if not hasattr(conn, "active_checkouts"):
            setattr(conn, "active_checkouts", 0)
        if not hasattr(conn, "closed"):
            setattr(conn, "closed", False)
        connections.append(conn)
        return conn

    def connect(database_url: str, **_kwargs: Any) -> _ConnT:
        assert database_url.startswith("postgresql://")
        return new_connection()

    class BoundConnectionPool(FakeConnectionPool):
        """Fake pool that owns one reusable connection."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.conn = new_connection()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    monkeypatch.setitem(
        sys.modules,
        "psycopg_pool",
        SimpleNamespace(ConnectionPool=BoundConnectionPool, PoolTimeout=PoolTimeout),
    )
    return connections


__all__ = ["FakeConnectionPool", "PoolTimeout", "install_fake_postgres_modules"]
