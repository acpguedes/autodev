"""Plan store factory preserving the historical ``PlanStore`` constructor."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from backend.persistence.postgres_adapter import PostgresPlanStore
from backend.persistence.sqlite_adapter import SQLitePlanStore


def PlanStore(db_path: Optional[Path] = None, database_url: str = ""):
    url = database_url or os.environ.get("DATABASE_URL", "")
    if db_path is None and (
        url.startswith("postgresql://") or url.startswith("postgres://")
    ):
        return PostgresPlanStore(database_url=url)
    return SQLitePlanStore(db_path=db_path)


__all__ = ["PlanStore"]
