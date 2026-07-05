"""Plan store factory preserving the historical ``PlanStore`` constructor."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from backend.persistence.postgres_adapter import PostgresPlanStore
from backend.persistence.sqlite_adapter import SQLitePlanStore


def PlanStore(
    db_path: Optional[Path] = None, database_url: str = ""
) -> PostgresPlanStore | SQLitePlanStore:
    """Build the plan store backend appropriate for the configured database URL.

    Args:
        db_path: SQLite database file path; forces the SQLite backend when given.
        database_url: Database URL; falls back to the ``DATABASE_URL`` env var.

    Returns:
        A :class:`PostgresPlanStore` for PostgreSQL URLs (when ``db_path`` is
        unset), otherwise a :class:`SQLitePlanStore`.
    """
    url = database_url or os.environ.get("DATABASE_URL", "")
    if db_path is None and (
        url.startswith("postgresql://") or url.startswith("postgres://")
    ):
        return PostgresPlanStore(database_url=url)
    return SQLitePlanStore(db_path=db_path)


__all__ = ["PlanStore"]
