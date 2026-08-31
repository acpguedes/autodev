"""PostgreSQL implementations of the persistence repository protocols.

Split by data domain across this package (E47-S4): see ``sessions.py``,
``runs.py``, ``messages.py``, ``eval_scoring.py`` (mixins composed by
``store.py``'s :class:`PostgresStore`) and ``plan_store.py``. This module
keeps the same import surface the single-file module previously exposed.
"""

from __future__ import annotations

from backend.persistence.postgres_adapter._shared import (
    _DEFAULT_DATABASE_URL,
    PostgresConnectionManager,
    PostgresPoolConfig,
    PostgresPoolExhaustedError,
)
from backend.persistence.postgres_adapter.plan_store import PostgresPlanStore
from backend.persistence.postgres_adapter.store import PostgresStore

__all__ = [
    "PostgresConnectionManager",
    "PostgresPlanStore",
    "PostgresPoolConfig",
    "PostgresPoolExhaustedError",
    "PostgresStore",
    "_DEFAULT_DATABASE_URL",
]
