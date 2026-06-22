"""Plan store — backward-compat re-export.

All SQL lives in ``backend.persistence.sqlite_adapter.SQLitePlanStore``.
``PlanStore`` is an alias so existing imports (``from backend.plans import PlanStore``)
keep working without change.
"""

from backend.persistence.sqlite_adapter import SQLitePlanStore as PlanStore

__all__ = ["PlanStore"]
