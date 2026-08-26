"""Per-step approval state machine for the ``/v2`` plan approval surface (E16-S2; E55).

The legacy plan document (:class:`backend.plans.models.PlanDocument`) stores
``steps`` as a plain ``list[str]`` of content with a single plan-level
``status`` — there is no column for per-step approval state. This module
layers a small, durable, tenant-scoped ``plan_step_state`` table on top of
that content so each step can move independently through:

``draft -> under_review -> approved | rejected -> executing -> completed``

Content edits are legal only while a step is ``draft`` or ``under_review``.
``approve``/``reject`` are legal only from ``under_review`` (steps are
auto-promoted out of ``draft`` on first read). ``execute`` is legal only
from ``approved`` — attempting to execute a ``rejected`` or still-``draft``/
``under_review`` step is an illegal transition. ``complete`` is legal only
from ``executing``.

The state names are intentionally generic (not tied to any single execution
mode) so E14-S3's approval/auto/hybrid execution modes — and, per E16-S2's
reuse note, E14-S5 — can drive the same machine: an "auto" mode simply skips
straight from ``under_review`` to ``approved`` without a human actor, while
"hybrid" mixes both, without any change to the state model itself.

Runs on both SQLite and PostgreSQL through the shared persistence contract
(E49, ADR-025; E55), following the same port pattern
:class:`~backend.quotas.store.QuotaStore` (E51) and
:class:`~backend.secret_store.store.SecretStore` (E52) established. Prior to
E55 this store connected to SQLite directly and silently diverted to a
dedicated file (``AUTODEV_PLAN_STEP_STATE_DB``) whenever ``DATABASE_URL`` was
unset or pointed at PostgreSQL -- the only store in the program that
accepted a PostgreSQL configuration and then quietly wrote somewhere else.
It now obtains its connection from the configured State Store, exactly like
every sibling store, and every operation is scoped to a tenant via
:meth:`StepApprovalStore._scope`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import os
from pathlib import Path
from typing import Any, Optional

from backend.persistence import contract
from backend.persistence.database import get_store
from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant


class StepState(StrEnum):
    """Lifecycle states for a single plan step (E16-S2-T3)."""

    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"


EDITABLE_STATES: frozenset[StepState] = frozenset({StepState.DRAFT, StepState.UNDER_REVIEW})
"""States in which a step's content may still be edited (E16-S2-T1)."""

REMOVABLE_STATES: frozenset[StepState] = frozenset(
    {StepState.DRAFT, StepState.UNDER_REVIEW, StepState.REJECTED}
)
"""States from which a step may be structurally removed (E17-S2).

Once a step is ``approved``/``executing``/``completed`` it is part of the
execution record and can no longer be deleted outright — only rejected
(which keeps it, dimmed, out of execution) or left as-is.
"""

_LEGAL_TRANSITIONS: dict[StepState, dict[str, StepState]] = {
    StepState.DRAFT: {"review": StepState.UNDER_REVIEW},
    StepState.UNDER_REVIEW: {
        "approve": StepState.APPROVED,
        "reject": StepState.REJECTED,
    },
    StepState.APPROVED: {"execute": StepState.EXECUTING},
    StepState.REJECTED: {},
    StepState.EXECUTING: {"complete": StepState.COMPLETED},
    StepState.COMPLETED: {},
}
"""Legal ``(current_state, action) -> next_state`` edges of the state machine."""


@dataclass(frozen=True)
class PlanStepRecord:
    """A single step's tracked approval state."""

    session_id: str
    step_index: int
    content: str
    state: StepState
    updated_at: str


def rollup_plan_state(states: list[StepState]) -> StepState:
    """Derive a plan-level state from its steps' individual states.

    Args:
        states: The state of every step in the plan.

    Returns:
        ``executing`` if any step is executing; ``completed`` only if every
        step is completed; ``rejected`` if any step was rejected;
        ``approved`` if every step is approved or completed; ``under_review``
        if any step has left ``draft``; otherwise ``draft``.
    """
    if not states:
        return StepState.DRAFT
    unique = set(states)
    if StepState.EXECUTING in unique:
        return StepState.EXECUTING
    if unique == {StepState.COMPLETED}:
        return StepState.COMPLETED
    if StepState.REJECTED in unique:
        return StepState.REJECTED
    if unique <= {StepState.APPROVED, StepState.COMPLETED}:
        return StepState.APPROVED
    if StepState.UNDER_REVIEW in unique:
        return StepState.UNDER_REVIEW
    return StepState.DRAFT


def legacy_step_state_db_path() -> Path:
    """Resolve the pre-E55 standalone SQLite file's path (migration input only).

    Prior to E55, :class:`StepApprovalStore` fell back to a dedicated SQLite
    file whenever ``DATABASE_URL`` was unset or pointed at PostgreSQL:
    ``AUTODEV_PLAN_STEP_STATE_DB`` (default ``./autodev_plan_step_state.db``).
    This helper resolves *that* legacy location purely so the E55-S3
    migration path can find and read any state left behind by a pre-E55
    install -- it is no longer used to decide where this store reads or
    writes. See ``AUTODEV_PLAN_STEP_STATE_DB`` in ``docs/config.md`` for the
    variable's current (local-only, migration-source) meaning.

    Returns:
        Absolute path to the legacy SQLite file, whether or not it exists.
    """
    fallback = os.environ.get("AUTODEV_PLAN_STEP_STATE_DB", "./autodev_plan_step_state.db")
    return Path(fallback).expanduser().resolve()


_ROW_COLUMNS = "session_id, step_index, content, state, updated_at"


def _row_to_record(row: tuple) -> PlanStepRecord:
    """Convert a positional ``plan_step_state`` row into a :class:`PlanStepRecord`.

    Args:
        row: A row shaped like :data:`_ROW_COLUMNS`
            (``session_id, step_index, content, state, updated_at``), from
            either backend.

    Returns:
        The corresponding immutable record.
    """
    return PlanStepRecord(
        session_id=row[0],
        step_index=row[1],
        content=row[2],
        state=StepState(row[3]),
        updated_at=row[4],
    )


class StepApprovalStore:
    """Durable, tenant-scoped per-step approval state, on either backend.

    Concurrency is serialized by the database, not by a process-local lock
    (E55-S2; a ``threading.Lock`` protects nothing across replicas or
    processes, which is exactly the gap this story closes). Every mutating
    method opens a single connection's transaction via
    :meth:`_begin_write` -- ``BEGIN IMMEDIATE`` on SQLite (a real,
    whole-database file lock, safe across threads and processes on one
    machine) and, on PostgreSQL, an explicit transaction whose critical read
    takes :meth:`_for_update`'s row lock (``SELECT ... FOR UPDATE``) on the
    one row being transitioned. :meth:`transition`, :meth:`update_content`,
    and :meth:`delete_step` additionally guard their ``UPDATE``/``DELETE``
    with the exact state read moments earlier (``WHERE ... AND state =
    ...``) and check the affected row count: a concurrent transaction that
    changed the row's state between the read and the write loses the row
    lock's wait and then fails this guard, so it is rejected outright (a
    :class:`ValueError`) rather than silently overwriting the winner's
    transition -- this is what makes "two replicas cannot both move a step
    out of ``under_review``" true for a genuine cross-process race, not just
    within one Python process.

    The ``plan_step_state`` table carries Row-Level Security on PostgreSQL
    (E50-S4): every operation calls :meth:`_scope` to set the
    ``app.tenant_id`` GUC inside the same transaction as its query (a no-op
    on SQLite, which has no RLS and is scoped by the explicit ``WHERE
    tenant_id = ...`` clauses already present in each query).
    """

    def __init__(self, db_path: Optional[Path] = None, *, store: Any = None) -> None:
        """Open the store against an explicit SQLite file, an injected store, or the configured one.

        Args:
            db_path: When given (and ``store`` is not), a SQLite file to open
                directly -- built into a dedicated
                :class:`~backend.persistence.sqlite_adapter.store.SQLiteStore`
                so tests can exercise real, independently-connected SQLite
                instances against the same file.
            store: An existing store exposing ``connect()`` (a
                :class:`~backend.persistence.sqlite_adapter.store.SQLiteStore`
                or ``PostgresStore``). Takes precedence over ``db_path``.
                Defaults to the process-wide configured store
                (:func:`backend.persistence.database.get_store`) when neither
                is given -- the path production takes, and the one that no
                longer ever produces a standalone SQLite file for a
                PostgreSQL ``DATABASE_URL``.

        Raises:
            TypeError: If the resolved store does not expose ``connect()``.
        """
        if store is None and db_path is not None:
            from backend.persistence.sqlite_adapter.store import SQLiteStore  # noqa: PLC0415

            store = SQLiteStore(f"sqlite:///{db_path}")
        self._store = store or get_store()
        if not hasattr(self._store, "connect"):
            raise TypeError("StepApprovalStore requires a durable store with connect()")

    # --------------------------------------------------------------- helpers

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        return contract.is_postgres(getattr(self._store, "database_url", ""))

    def _sql(self, template: str) -> str:
        """Substitute this store's dialect placeholder into a SQL template."""
        return contract.sql(template, self._is_postgres)

    def _connect(self) -> Any:
        """Open a fresh connection from the backing store."""
        return self._store.connect()

    def _begin_write(self, conn: Any) -> None:
        """Start a write transaction eagerly on SQLite; a no-op on PostgreSQL."""
        contract.begin_write(conn, self._is_postgres)

    def _for_update(self) -> str:
        """Return the row-lock clause for a critical-section ``SELECT``."""
        return contract.for_update_clause(self._is_postgres)

    def _scope(self, conn: Any, tenant_id: str) -> None:
        """Set the PostgreSQL tenant GUC for this transaction; a no-op on SQLite."""
        if self._is_postgres:
            set_postgres_tenant(conn, tenant_id)

    def _lock_session_for_write(self, conn: Any, tenant_id: str, session_id: str) -> None:
        """Serialize every writer for one session's step list against each other, on PostgreSQL.

        :meth:`append_step` counts existing rows (``MAX(step_index)``) and
        then conditionally inserts a new one -- the same "phantom row" shape
        E51-S2 identified for quota leases/reservations, where ``SELECT ...
        FOR UPDATE`` alone cannot protect the insert because the row it
        would lock does not exist yet. SQLite's :meth:`_begin_write`
        (``BEGIN IMMEDIATE``) already closes this gap with a whole-database
        write lock, so this is a no-op there. On PostgreSQL, a
        transaction-scoped advisory lock keyed by ``(tenant_id,
        session_id)`` (released automatically at commit or rollback)
        serializes every such writer for the same session.

        Args:
            conn: Open connection with an in-progress write transaction.
            tenant_id: Tenant the session's plan belongs to.
            session_id: The owning session.
        """
        if self._is_postgres:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{tenant_id}:{session_id}",))

    @staticmethod
    def _now() -> str:
        """Return the current UTC timestamp in ISO-8601 form.

        Returns:
            An ISO-8601 timestamp string.
        """
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------- reads

    def ensure_steps(
        self, session_id: str, contents: list[str], *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[PlanStepRecord]:
        """Seed rows for step indices not yet tracked, then return every step.

        Existing rows (and their state/content) are left untouched — this is
        purely additive seeding from the legacy plan document's content, so
        repeated calls are idempotent.

        Args:
            session_id: The owning session.
            contents: The plan's step contents, in order.
            tenant_id: Tenant the plan belongs to.

        Returns:
            Every tracked step for the session, ordered by index.
        """
        now = self._now()
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            for index, content in enumerate(contents):
                conn.execute(
                    self._sql(
                        "INSERT INTO plan_step_state "
                        "(tenant_id, session_id, step_index, content, state, updated_at) "
                        "VALUES ({p}, {p}, {p}, {p}, {p}, {p}) "
                        "ON CONFLICT (session_id, step_index) DO NOTHING"
                    ),
                    (tenant_id, session_id, index, content, StepState.DRAFT.value, now),
                )
            conn.commit()
            rows = conn.execute(
                self._sql(
                    f"SELECT {_ROW_COLUMNS} FROM plan_step_state "
                    "WHERE tenant_id = {p} AND session_id = {p} ORDER BY step_index"
                ),
                (tenant_id, session_id),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def list_steps(
        self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[PlanStepRecord]:
        """List every tracked step for a session, ordered by index.

        Args:
            session_id: The owning session.
            tenant_id: Tenant the plan belongs to.

        Returns:
            The tracked steps; empty if none have been seeded yet.
        """
        conn = self._connect()
        self._scope(conn, tenant_id)
        rows = conn.execute(
            self._sql(
                f"SELECT {_ROW_COLUMNS} FROM plan_step_state "
                "WHERE tenant_id = {p} AND session_id = {p} ORDER BY step_index"
            ),
            (tenant_id, session_id),
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def get_step(
        self, session_id: str, step_index: int, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> Optional[PlanStepRecord]:
        """Fetch a single tracked step.

        Args:
            session_id: The owning session.
            step_index: Zero-based step position.
            tenant_id: Tenant the plan belongs to.

        Returns:
            The step record, or ``None`` if not tracked.
        """
        conn = self._connect()
        self._scope(conn, tenant_id)
        row = conn.execute(
            self._sql(
                f"SELECT {_ROW_COLUMNS} FROM plan_step_state "
                "WHERE tenant_id = {p} AND session_id = {p} AND step_index = {p}"
            ),
            (tenant_id, session_id, step_index),
        ).fetchone()
        return _row_to_record(row) if row is not None else None

    # ------------------------------------------------------------ writes

    def update_content(
        self,
        session_id: str,
        step_index: int,
        content: str,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> PlanStepRecord:
        """Overwrite a step's content while it is still editable.

        Args:
            session_id: The owning session.
            step_index: Zero-based step position.
            content: The new step content.
            tenant_id: Tenant the plan belongs to.

        Returns:
            The updated record.

        Raises:
            KeyError: If the step is not tracked.
            ValueError: If the step is not in an editable state, including
                one that left :data:`EDITABLE_STATES` in a concurrent
                transaction between this method's read and its write.
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            row = conn.execute(
                self._sql(
                    f"SELECT {_ROW_COLUMNS} FROM plan_step_state "
                    "WHERE tenant_id = {p} AND session_id = {p} AND step_index = {p}"
                    + self._for_update()
                ),
                (tenant_id, session_id, step_index),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"Step {step_index} not found for session {session_id!r}.")
            current = _row_to_record(row)
            if current.state not in EDITABLE_STATES:
                conn.rollback()
                raise ValueError(
                    f"Cannot edit step {step_index} in state {current.state.value!r}; "
                    "only draft/under_review steps are editable."
                )
            now = self._now()
            # Guarded by the exact state just read: a concurrent transition
            # that moved the step out of an editable state between the read
            # above and this write affects zero rows here rather than
            # silently overwriting content past its approval decision.
            cursor = conn.execute(
                self._sql(
                    "UPDATE plan_step_state SET content = {p}, updated_at = {p} "
                    "WHERE tenant_id = {p} AND session_id = {p} AND step_index = {p} AND state = {p}"
                ),
                (content, now, tenant_id, session_id, step_index, current.state.value),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                raise ValueError(
                    f"Cannot edit step {step_index}: its state changed concurrently "
                    "since it was read."
                )
            conn.commit()
            return PlanStepRecord(session_id, step_index, content, current.state, now)

    def append_step(
        self, session_id: str, content: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> PlanStepRecord:
        """Append a new ``draft`` step to the end of a session's tracked plan.

        Args:
            session_id: The owning session.
            content: The new step's content.
            tenant_id: Tenant the plan belongs to.

        Returns:
            The newly created step record, in the ``draft`` state.
        """
        now = self._now()
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            self._lock_session_for_write(conn, tenant_id, session_id)
            row = conn.execute(
                self._sql(
                    "SELECT COALESCE(MAX(step_index), -1) FROM plan_step_state "
                    "WHERE tenant_id = {p} AND session_id = {p}"
                ),
                (tenant_id, session_id),
            ).fetchone()
            next_index = row[0] + 1
            conn.execute(
                self._sql(
                    "INSERT INTO plan_step_state "
                    "(tenant_id, session_id, step_index, content, state, updated_at) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p})"
                ),
                (tenant_id, session_id, next_index, content, StepState.DRAFT.value, now),
            )
            conn.commit()
        return PlanStepRecord(session_id, next_index, content, StepState.DRAFT, now)

    def delete_step(
        self, session_id: str, step_index: int, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[PlanStepRecord]:
        """Remove a step and reindex subsequent steps to stay contiguous.

        Args:
            session_id: The owning session.
            step_index: Zero-based position of the step to remove.
            tenant_id: Tenant the plan belongs to.

        Returns:
            Every remaining tracked step for the session, ordered by index.

        Raises:
            KeyError: If the step is not tracked.
            ValueError: If the step is not in :data:`REMOVABLE_STATES` (only
                ``draft``/``under_review``/``rejected`` steps may be removed),
                including one that left :data:`REMOVABLE_STATES` in a
                concurrent transaction between this method's read and its
                write.
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            self._lock_session_for_write(conn, tenant_id, session_id)
            row = conn.execute(
                self._sql(
                    f"SELECT {_ROW_COLUMNS} FROM plan_step_state "
                    "WHERE tenant_id = {p} AND session_id = {p} AND step_index = {p}"
                    + self._for_update()
                ),
                (tenant_id, session_id, step_index),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"Step {step_index} not found for session {session_id!r}.")
            current = _row_to_record(row)
            if current.state not in REMOVABLE_STATES:
                conn.rollback()
                raise ValueError(
                    f"Cannot remove step {step_index} in state {current.state.value!r}; "
                    "only draft/under_review/rejected steps can be removed."
                )
            # Guarded by the exact state just read: a concurrent transition
            # that moved the step out of a removable state between the read
            # above and this write affects zero rows here rather than
            # silently deleting a step that just became part of the
            # execution record.
            cursor = conn.execute(
                self._sql(
                    "DELETE FROM plan_step_state "
                    "WHERE tenant_id = {p} AND session_id = {p} AND step_index = {p} AND state = {p}"
                ),
                (tenant_id, session_id, step_index, current.state.value),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                raise ValueError(
                    f"Cannot remove step {step_index}: its state changed concurrently "
                    "since it was read."
                )
            remaining_rows = conn.execute(
                self._sql(
                    f"SELECT {_ROW_COLUMNS} FROM plan_step_state "
                    "WHERE tenant_id = {p} AND session_id = {p} ORDER BY step_index"
                ),
                (tenant_id, session_id),
            ).fetchall()
            now = self._now()
            reindexed: list[PlanStepRecord] = []
            # Ascending order guarantees each target slot is already vacated
            # by the time we reach it, so no PRIMARY KEY collision occurs
            # within this single transaction.
            for new_index, remaining_row in enumerate(remaining_rows):
                record = _row_to_record(remaining_row)
                if record.step_index != new_index:
                    conn.execute(
                        self._sql(
                            "UPDATE plan_step_state SET step_index = {p}, updated_at = {p} "
                            "WHERE tenant_id = {p} AND session_id = {p} AND step_index = {p}"
                        ),
                        (new_index, now, tenant_id, session_id, record.step_index),
                    )
                    record = PlanStepRecord(session_id, new_index, record.content, record.state, now)
                reindexed.append(record)
            conn.commit()
        return reindexed

    def transition(
        self, session_id: str, step_index: int, action: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> tuple[StepState, PlanStepRecord]:
        """Atomically apply a state-machine action to a step.

        Args:
            session_id: The owning session.
            step_index: Zero-based step position.
            action: One of ``"review"``, ``"approve"``, ``"reject"``,
                ``"execute"``, ``"complete"``.
            tenant_id: Tenant the plan belongs to.

        Returns:
            A tuple of ``(previous_state, updated_record)``.

        Raises:
            KeyError: If the step is not tracked.
            ValueError: If ``action`` is not legal from the step's current
                state, including a state a concurrent transaction moved the
                step to between this method's read and its write (E55-S2:
                exactly one of two racing transitions wins; the other is
                rejected, never silently overwritten).
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            row = conn.execute(
                self._sql(
                    f"SELECT {_ROW_COLUMNS} FROM plan_step_state "
                    "WHERE tenant_id = {p} AND session_id = {p} AND step_index = {p}"
                    + self._for_update()
                ),
                (tenant_id, session_id, step_index),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"Step {step_index} not found for session {session_id!r}.")
            current = _row_to_record(row)
            next_state = _LEGAL_TRANSITIONS[current.state].get(action)
            if next_state is None:
                conn.rollback()
                raise ValueError(
                    f"Cannot {action} step {step_index} while it is {current.state.value!r}."
                )
            now = self._now()
            # Guarded by the exact state just read: on PostgreSQL, a second
            # transaction blocked on this row's FOR UPDATE lock re-reads the
            # winner's already-committed state once granted, so its own
            # _LEGAL_TRANSITIONS lookup for the *original* action against
            # that new state is what actually rejects it (this UPDATE guard
            # is defense in depth for that path, and the only thing standing
            # between a correct rejection and a silent overwrite on a
            # storage layer without row locking).
            cursor = conn.execute(
                self._sql(
                    "UPDATE plan_step_state SET state = {p}, updated_at = {p} "
                    "WHERE tenant_id = {p} AND session_id = {p} AND step_index = {p} AND state = {p}"
                ),
                (next_state.value, now, tenant_id, session_id, step_index, current.state.value),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                raise ValueError(
                    f"Cannot {action} step {step_index}: its state changed concurrently "
                    "since it was read."
                )
            conn.commit()
            return current.state, PlanStepRecord(session_id, step_index, current.content, next_state, now)

    # ------------------------------------------------------- migration (E55-S3)

    def import_legacy_row(
        self,
        tenant_id: str,
        session_id: str,
        step_index: int,
        content: str,
        state: str,
        updated_at: str,
    ) -> None:
        """Insert or replace one step's exact historical state, bypassing the state machine.

        For :mod:`backend.persistence.step_state_migration` only, restoring
        rows read from a pre-E55 standalone SQLite file verbatim -- content,
        state, and timestamp exactly as they were, with no transition
        validation, since a migration is not a live approval decision.
        Idempotent (``ON CONFLICT ... DO UPDATE``): migrating the same
        legacy file twice converges rather than erroring or duplicating.

        Args:
            tenant_id: Tenant to write the row under (the legacy row's own
                ``tenant_id``, or :data:`~backend.persistence.tenancy.DEFAULT_TENANT_ID`
                for a pre-E50-S3 legacy file that never had the column).
            session_id: The owning session.
            step_index: Zero-based step position.
            content: The step's content, exactly as read from the legacy file.
            state: The step's state value, exactly as read from the legacy file.
            updated_at: The step's last-updated timestamp, exactly as read
                from the legacy file.
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO plan_step_state "
                    "(tenant_id, session_id, step_index, content, state, updated_at) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}) "
                    "ON CONFLICT (session_id, step_index) DO UPDATE SET "
                    "tenant_id = excluded.tenant_id, content = excluded.content, "
                    "state = excluded.state, updated_at = excluded.updated_at"
                ),
                (tenant_id, session_id, step_index, content, state, updated_at),
            )
            conn.commit()


__all__ = [
    "EDITABLE_STATES",
    "REMOVABLE_STATES",
    "PlanStepRecord",
    "StepApprovalStore",
    "StepState",
    "legacy_step_state_db_path",
    "rollup_plan_state",
]
