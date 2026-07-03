"""Durable store factory and backward-compat aliases.

All SQL lives in ``sqlite_adapter.py``.  This module exposes the same public
names used before the Repository-pattern refactor so existing imports keep
working without change.
"""

from __future__ import annotations

from functools import lru_cache

from backend.config.settings import get_settings
from backend.persistence.sqlite_adapter import SQLiteStore


DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"

# Backward-compat alias: code that imports DurableStore continues to work.
DurableStore = SQLiteStore


@lru_cache(maxsize=1)
def get_store():
    """Return a cached store keyed off DATABASE_URL.

    Returns SQLite for local-first URLs and PostgreSQL for production URLs.
    """
    url = get_settings().database_url
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        from backend.persistence.postgres_adapter import PostgresStore  # noqa: PLC0415
        return PostgresStore(url)
    return SQLiteStore(url)


def reset_store_cache() -> None:
    """Clear the cached store, mainly for tests."""
    get_store.cache_clear()
