"""SQLite-backed store composing every persistence-protocol mixin (E47-S4)."""

from __future__ import annotations

import sqlite3

from backend.persistence.migrations import MigrationRunner
from backend.persistence.migrations.versions import STORE_MIGRATIONS
from backend.persistence.sqlite_adapter._shared import _DEFAULT_DATABASE_URL, _resolve_db_path
from backend.persistence.sqlite_adapter.eval_scoring import _EvalScoringMixin
from backend.persistence.sqlite_adapter.messages import _MessagesMixin
from backend.persistence.sqlite_adapter.runs import _RunsMixin
from backend.persistence.sqlite_adapter.sessions import _SessionsMixin


class SQLiteStore(_SessionsMixin, _RunsMixin, _MessagesMixin, _EvalScoringMixin):
    """SQLite-backed store implementing SessionRepository, RunRepository,
    MessageRepository, EvalResultRepository, and ScoreSnapshotRepository in a
    single connection-per-call style.

    Every read/write is scoped to a ``tenant_id`` (default
    :data:`~backend.persistence.tenancy.DEFAULT_TENANT_ID`), per the E8-S1
    scoped multi-tenancy slice (ADR-010). SQLite has no Row-Level Security
    equivalent, so isolation is enforced here by appending
    :func:`~backend.persistence.tenancy.sqlite_tenant_clause` to hand-written
    queries on the tenant-scoped tables (``sessions``, ``runs``, ``messages``,
    ``eval_results``, ``score_snapshots``). ``run_steps`` and
    ``score_snapshot_promotions`` have no ``tenant_id`` column of their own by
    design — they are scoped transitively through their parent row's tenant
    via a ``JOIN``.

    Split by data domain across this package's modules (E47-S4):
    :mod:`sessions`, :mod:`runs`, :mod:`messages`, :mod:`eval_scoring`. Each
    mixin is independently readable and type-checkable against
    ``_ConnectionOwner``; only this class provides the real ``connect()``.
    """

    def __init__(self, database_url: str = _DEFAULT_DATABASE_URL) -> None:
        self.database_url = database_url
        self._database_path = _resolve_db_path(database_url)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            MigrationRunner(conn, STORE_MIGRATIONS, namespace="store").run_pending()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._database_path)
        conn.row_factory = sqlite3.Row
        return conn


__all__ = ["SQLiteStore"]
