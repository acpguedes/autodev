"""Durable store factory and backward-compat aliases.

All SQL lives in ``sqlite_adapter.py``.  This module exposes the same public
names used before the Repository-pattern refactor so existing imports keep
working without change.
"""

from __future__ import annotations

import os
from functools import lru_cache

from backend.persistence.sqlite_adapter import SQLiteStore


DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"

# Backward-compat alias: code that imports DurableStore continues to work.
DurableStore = SQLiteStore


@lru_cache(maxsize=1)
def get_store() -> SQLiteStore:
    """Return a cached store keyed off DATABASE_URL.

    Raises ``NotImplementedError`` when the URL is a postgres:// URL (the
    PostgresStore scaffold is not yet fully implemented).
    """
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        from backend.persistence.postgres_adapter import PostgresStore  # noqa: PLC0415
        return PostgresStore(url)  # type: ignore[return-value]  # will raise NIE
    return SQLiteStore(url)


def reset_store_cache() -> None:
    """Clear the cached store, mainly for tests."""
    get_store.cache_clear()
