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
    PostgresDeadlockError,
    PostgresPoolConfig,
    PostgresPoolExhaustedError,
    PostgresRetryConfig,
    PostgresSerializationFailureError,
    classify_postgres_error,
    pool_retry_config_from_settings,
    run_with_postgres_retry,
)
from backend.persistence.postgres_adapter.plan_store import PostgresPlanStore
from backend.persistence.postgres_adapter.store import PostgresStore

__all__ = [
    "PostgresConnectionManager",
    "PostgresDeadlockError",
    "PostgresPlanStore",
    "PostgresPoolConfig",
    "PostgresPoolExhaustedError",
    "PostgresRetryConfig",
    "PostgresSerializationFailureError",
    "PostgresStore",
    "classify_postgres_error",
    "pool_retry_config_from_settings",
    "run_with_postgres_retry",
    "_DEFAULT_DATABASE_URL",
]
