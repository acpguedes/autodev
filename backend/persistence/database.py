"""Durable store factory and backward-compat aliases.

All SQL lives in ``sqlite_adapter.py``.  This module exposes the same public
names used before the Repository-pattern refactor so existing imports keep
working without change.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from backend.config.settings import get_settings
from backend.persistence.contract import is_postgres
from backend.persistence.sqlite_adapter import SQLiteStore

if TYPE_CHECKING:
    from backend.persistence.postgres_adapter import PostgresStore


DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"

#: Backward-compat, SQLite-only alias (E49-S4, ADR-025): predates
#: :func:`get_store`'s dialect switch and is used exclusively by tests and
#: :mod:`backend.sdk.testing` to build an ephemeral SQLite-backed store
#: directly — it always returns :class:`SQLiteStore` regardless of
#: ``DATABASE_URL`` and is never constructed by production code (which uses
#: :func:`get_store`). Kept as-is rather than renamed: ~30 call sites, all
#: test-only, with no behavior change to make renaming worth the churn.
DurableStore = SQLiteStore


@lru_cache(maxsize=1)
def get_store() -> "SQLiteStore | PostgresStore":
    """Return a cached store keyed off DATABASE_URL.

    Returns SQLite for local-first URLs and PostgreSQL for production URLs.

    Returns:
        A :class:`SQLiteStore` or ``PostgresStore`` instance, depending on
        ``DATABASE_URL``.
    """
    url = get_settings().database_url
    if is_postgres(url):
        from backend.persistence.postgres_adapter import PostgresStore  # noqa: PLC0415
        return PostgresStore(url)
    return SQLiteStore(url)


def reset_store_cache() -> None:
    """Clear the cached store, mainly for tests."""
    get_store.cache_clear()
