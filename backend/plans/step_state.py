"""Per-step approval state machine for the ``/v2`` plan approval surface (E16-S2).

The legacy plan document (:class:`backend.plans.models.PlanDocument`) stores
``steps`` as a plain ``list[str]`` of content with a single plan-level
``status`` — there is no column for per-step approval state. This module
layers a small, durable, lock-guarded SQLite table on top of that content so
each step can move independently through:

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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import os
from pathlib import Path
import sqlite3
import threading
from typing import Optional


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


def _resolve_step_state_db_path() -> Path:
    """Resolve the SQLite file backing per-step approval state.

    Reuses the same SQLite file as the legacy plan store when
    ``DATABASE_URL`` points at SQLite, keeping step state physically
    co-located with step content. Otherwise (unset, or a PostgreSQL URL)
    falls back to a dedicated SQLite file: per-step approval state is a new,
    additive v2-only concern and does not require extending the PostgreSQL
    schema/migrations for this story.

    Returns:
        Absolute path to the SQLite file to open.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        return Path(db_url.removeprefix("sqlite:///")).expanduser().resolve()
    if db_url.startswith("sqlite://"):
        return Path(db_url.removeprefix("sqlite://")).expanduser().resolve()
    fallback = os.environ.get("AUTODEV_PLAN_STEP_STATE_DB", "./autodev_plan_step_state.db")
    return Path(fallback).expanduser().resolve()


class StepApprovalStore:
    """SQLite-backed, lock-guarded per-step approval state.

    Every read-check-write sequence (content edit, transition) is guarded by
    both a process-local :class:`threading.Lock` and a single SQLite
    connection's transaction, so concurrent approve/reject/execute calls for
    the same step cannot race into a corrupted or duplicated transition
    (E16-S2-T3 atomicity requirement).
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Open (creating if needed) the SQLite-backed step-state table.

        Args:
            db_path: Explicit SQLite file path; defaults to
                :func:`_resolve_step_state_db_path`.
        """
        self._db_path = db_path or _resolve_step_state_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_step_state (
                    session_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, step_index)
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """Open a fresh connection to the step-state database.

        Returns:
            A connection with row access by column name.
        """
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        """Return the current UTC timestamp in ISO-8601 form.

        Returns:
            An ISO-8601 timestamp string.
        """
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> PlanStepRecord:
        """Convert a raw SQLite row into a :class:`PlanStepRecord`.

        Args:
            row: A row from the ``plan_step_state`` table.

        Returns:
            The corresponding immutable record.
        """
        return PlanStepRecord(
            session_id=row["session_id"],
            step_index=row["step_index"],
            content=row["content"],
            state=StepState(row["state"]),
            updated_at=row["updated_at"],
        )

    def ensure_steps(self, session_id: str, contents: list[str]) -> list[PlanStepRecord]:
        """Seed rows for step indices not yet tracked, then return every step.

        Existing rows (and their state/content) are left untouched — this is
        purely additive seeding from the legacy plan document's content, so
        repeated calls are idempotent.

        Args:
            session_id: The owning session.
            contents: The plan's step contents, in order.

        Returns:
            Every tracked step for the session, ordered by index.
        """
        now = self._now()
        with self._lock, self._connect() as conn:
            for index, content in enumerate(contents):
                conn.execute(
                    """
                    INSERT INTO plan_step_state (session_id, step_index, content, state, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, step_index) DO NOTHING
                    """,
                    (session_id, index, content, StepState.DRAFT.value, now),
                )
            conn.commit()
            rows = conn.execute(
                "SELECT * FROM plan_step_state WHERE session_id = ? ORDER BY step_index",
                (session_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_steps(self, session_id: str) -> list[PlanStepRecord]:
        """List every tracked step for a session, ordered by index.

        Args:
            session_id: The owning session.

        Returns:
            The tracked steps; empty if none have been seeded yet.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM plan_step_state WHERE session_id = ? ORDER BY step_index",
                (session_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_step(self, session_id: str, step_index: int) -> Optional[PlanStepRecord]:
        """Fetch a single tracked step.

        Args:
            session_id: The owning session.
            step_index: Zero-based step position.

        Returns:
            The step record, or ``None`` if not tracked.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plan_step_state WHERE session_id = ? AND step_index = ?",
                (session_id, step_index),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def update_content(self, session_id: str, step_index: int, content: str) -> PlanStepRecord:
        """Overwrite a step's content while it is still editable.

        Args:
            session_id: The owning session.
            step_index: Zero-based step position.
            content: The new step content.

        Returns:
            The updated record.

        Raises:
            KeyError: If the step is not tracked.
            ValueError: If the step is not in an editable state.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plan_step_state WHERE session_id = ? AND step_index = ?",
                (session_id, step_index),
            ).fetchone()
            if row is None:
                raise KeyError(f"Step {step_index} not found for session {session_id!r}.")
            current = self._row_to_record(row)
            if current.state not in EDITABLE_STATES:
                raise ValueError(
                    f"Cannot edit step {step_index} in state {current.state.value!r}; "
                    "only draft/under_review steps are editable."
                )
            now = self._now()
            conn.execute(
                "UPDATE plan_step_state SET content = ?, updated_at = ? WHERE session_id = ? AND step_index = ?",
                (content, now, session_id, step_index),
            )
            conn.commit()
            return PlanStepRecord(session_id, step_index, content, current.state, now)

    def append_step(self, session_id: str, content: str) -> PlanStepRecord:
        """Append a new ``draft`` step to the end of a session's tracked plan.

        Args:
            session_id: The owning session.
            content: The new step's content.

        Returns:
            The newly created step record, in the ``draft`` state.
        """
        now = self._now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(step_index), -1) AS max_index FROM plan_step_state "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            next_index = row["max_index"] + 1
            conn.execute(
                """
                INSERT INTO plan_step_state (session_id, step_index, content, state, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, next_index, content, StepState.DRAFT.value, now),
            )
            conn.commit()
        return PlanStepRecord(session_id, next_index, content, StepState.DRAFT, now)

    def delete_step(self, session_id: str, step_index: int) -> list[PlanStepRecord]:
        """Remove a step and reindex subsequent steps to stay contiguous.

        Args:
            session_id: The owning session.
            step_index: Zero-based position of the step to remove.

        Returns:
            Every remaining tracked step for the session, ordered by index.

        Raises:
            KeyError: If the step is not tracked.
            ValueError: If the step is not in :data:`REMOVABLE_STATES` (only
                ``draft``/``under_review``/``rejected`` steps may be removed).
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plan_step_state WHERE session_id = ? AND step_index = ?",
                (session_id, step_index),
            ).fetchone()
            if row is None:
                raise KeyError(f"Step {step_index} not found for session {session_id!r}.")
            current = self._row_to_record(row)
            if current.state not in REMOVABLE_STATES:
                raise ValueError(
                    f"Cannot remove step {step_index} in state {current.state.value!r}; "
                    "only draft/under_review/rejected steps can be removed."
                )
            conn.execute(
                "DELETE FROM plan_step_state WHERE session_id = ? AND step_index = ?",
                (session_id, step_index),
            )
            remaining_rows = conn.execute(
                "SELECT * FROM plan_step_state WHERE session_id = ? ORDER BY step_index",
                (session_id,),
            ).fetchall()
            now = self._now()
            reindexed: list[PlanStepRecord] = []
            # Ascending order guarantees each target slot is already vacated
            # by the time we reach it, so no PRIMARY KEY collision occurs
            # within this single transaction.
            for new_index, remaining_row in enumerate(remaining_rows):
                record = self._row_to_record(remaining_row)
                if record.step_index != new_index:
                    conn.execute(
                        "UPDATE plan_step_state SET step_index = ?, updated_at = ? "
                        "WHERE session_id = ? AND step_index = ?",
                        (new_index, now, session_id, record.step_index),
                    )
                    record = PlanStepRecord(session_id, new_index, record.content, record.state, now)
                reindexed.append(record)
            conn.commit()
        return reindexed

    def transition(
        self, session_id: str, step_index: int, action: str
    ) -> tuple[StepState, PlanStepRecord]:
        """Atomically apply a state-machine action to a step.

        Args:
            session_id: The owning session.
            step_index: Zero-based step position.
            action: One of ``"review"``, ``"approve"``, ``"reject"``,
                ``"execute"``, ``"complete"``.

        Returns:
            A tuple of ``(previous_state, updated_record)``.

        Raises:
            KeyError: If the step is not tracked.
            ValueError: If ``action`` is not legal from the step's current
                state.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plan_step_state WHERE session_id = ? AND step_index = ?",
                (session_id, step_index),
            ).fetchone()
            if row is None:
                raise KeyError(f"Step {step_index} not found for session {session_id!r}.")
            current = self._row_to_record(row)
            next_state = _LEGAL_TRANSITIONS[current.state].get(action)
            if next_state is None:
                raise ValueError(
                    f"Cannot {action} step {step_index} while it is {current.state.value!r}."
                )
            now = self._now()
            conn.execute(
                "UPDATE plan_step_state SET state = ?, updated_at = ? WHERE session_id = ? AND step_index = ?",
                (next_state.value, now, session_id, step_index),
            )
            conn.commit()
            return current.state, PlanStepRecord(session_id, step_index, current.content, next_state, now)


__all__ = [
    "EDITABLE_STATES",
    "REMOVABLE_STATES",
    "PlanStepRecord",
    "StepApprovalStore",
    "StepState",
    "rollup_plan_state",
]
