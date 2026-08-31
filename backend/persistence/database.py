"""Durable store factory and backward-compat aliases.

All SQL lives in ``sqlite_adapter.py``.  This module exposes the same public
names used before the Repository-pattern refactor so existing imports keep
working without change.
"""

from __future__ import annotations

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
#: Not a dual-backend contract harness (E56-S1-T3): for that, see
#: :mod:`backend.tests.persistence_contract`, which builds
#: :class:`SQLiteStore`/``PostgresStore`` directly per backend instead of
#: through this alias.
DurableStore = SQLiteStore

_store_cache: "SQLiteStore | PostgresStore | None" = None


def get_store() -> "SQLiteStore | PostgresStore":
    """Return a cached store keyed off DATABASE_URL.

    Returns SQLite for local-first URLs and PostgreSQL for production URLs.

    Returns:
        A :class:`SQLiteStore` or ``PostgresStore`` instance, depending on
        ``DATABASE_URL``.
    """
    global _store_cache
    if _store_cache is None:
        url = get_settings().database_url
        if is_postgres(url):
            from backend.persistence.postgres_adapter import PostgresStore  # noqa: PLC0415

            _store_cache = PostgresStore(url)
        else:
            _store_cache = SQLiteStore(url)
    return _store_cache


def get_cached_store() -> "SQLiteStore | PostgresStore | None":
    """Return the process-wide store if one is already constructed, without constructing one.

    Readiness (E60-S4-T2) uses this to report live PostgreSQL pool
    saturation without the side effect of building a pool (and dialing the
    database) merely because something asked for it.

    Returns:
        The cached store, or ``None`` if :func:`get_store` has not been
        called yet in this process.
    """
    return _store_cache


def reset_store_cache() -> None:
    """Clear the cached store, closing any owned PostgreSQL pool first."""
    global _store_cache
    store = _store_cache
    _store_cache = None
    close = getattr(store, "close", None)
    if callable(close):
        close()
