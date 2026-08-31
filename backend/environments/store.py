"""Durable store for environment lifecycle records and policy decisions (E32-S3/S4; E54).

Runs on both SQLite and PostgreSQL through the shared persistence contract
(E49, ADR-025; E54), following the same port pattern
:class:`~backend.quotas.store.QuotaStore` (E51) and
:class:`~backend.secret_store.store.SecretStore` (E52) established.

Both tables carry Row-Level Security on PostgreSQL (E50-S4): every
tenant-scoped operation calls
:func:`~backend.persistence.tenancy.set_postgres_tenant` to set the
``app.tenant_id`` GUC inside the same transaction as its query, via
:meth:`EnvironmentStore._scope` (a no-op on SQLite, which has no RLS and is
scoped by the ``WHERE tenant_id = ...`` clauses already present in each
query). Because PostgreSQL's Row-Level Security policy on these tables is
``USING (tenant_id = current_setting('app.tenant_id', true))`` with
``FORCE ROW LEVEL SECURITY``, every read or write against either table
requires the caller to know and pass the owning tenant -- unlike the
SQLite-only original, every lookup here (``get``, ``mark_status``,
``list_for_run``, ``list_decisions_for_run``, ``list_expired_active``) takes
an explicit ``tenant_id`` for this reason, not only as a defense-in-depth
filter.

Lifecycle transitions are idempotent: :meth:`EnvironmentStore.mark_status`
is a no-op once a record is already in a terminal status, so a retried
teardown (e.g. after a crash mid-transition) cannot corrupt state or
double-record a timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from backend.persistence import contract
from backend.persistence.database import get_store
from backend.persistence.tenancy import set_postgres_tenant

#: Statuses from which no further transition is accepted (E54-S1-T3): once an
#: environment record reaches one of these, :meth:`EnvironmentStore.mark_status`
#: is a no-op, which is what makes a retried teardown or a claim raced by
#: another replica safe rather than state-corrupting.
_TERMINAL_STATUSES = ("torn_down", "orphaned")

_ENV_COLUMNS = (
    "environment_id, run_id, tenant_id, backend_kind, profile_id, profile_hash, "
    "workspace_path, status, created_at, expires_at, torn_down_at"
)
_DECISION_COLUMNS = (
    "decision_id, environment_id, run_id, tenant_id, category, target, allowed, "
    "reason, decided_at"
)


def _now() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


def _now_plus(seconds: int) -> str:
    """Return an ISO-8601 timestamp *seconds* in the future."""
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


@dataclass(frozen=True, slots=True)
class EnvironmentRecord:
    """One durably persisted environment lifecycle record.

    Attributes:
        environment_id: Unique identifier for the provisioned instance.
        run_id: Orchestrator run this environment was provisioned for.
        tenant_id: Tenant the run belongs to.
        backend_kind: Resolved backend that provisioned this instance.
        profile_id: The environment profile's identifier.
        profile_hash: The environment profile's content hash (evidence, E32-S4-T2).
        workspace_path: Host path backing the workspace mount.
        status: ``"active"``, ``"torn_down"``, or ``"orphaned"``.
        created_at: When this instance was provisioned.
        expires_at: TTL deadline; past this without teardown, the instance
            is reaped as an orphan.
        torn_down_at: When teardown completed, if it has.
    """

    environment_id: str
    run_id: str
    tenant_id: str
    backend_kind: str
    profile_id: str
    profile_hash: str
    workspace_path: str
    status: str
    created_at: str
    expires_at: str
    torn_down_at: Optional[str] = None


@dataclass(frozen=True, slots=True)
class EnvironmentDecisionRecord:
    """One durably persisted policy decision on a provisioned environment (E32-S4-T1).

    Attributes:
        decision_id: Unique identifier.
        environment_id: The environment this decision was evaluated against.
        run_id: Orchestrator run the environment belongs to.
        tenant_id: Tenant the run belongs to.
        category: ``"network"`` or ``"filesystem"``.
        target: The host or path the decision concerned.
        allowed: Whether the access was permitted.
        reason: Human-readable reason.
        decided_at: When the decision was recorded.
    """

    decision_id: str
    environment_id: str
    run_id: str
    tenant_id: str
    category: str
    target: str
    allowed: bool
    reason: str
    decided_at: str


class EnvironmentStore:
    """Durable store for environment lifecycle records and decisions, on either backend."""

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
                is given -- the path production takes.

        Raises:
            TypeError: If the resolved store does not expose ``connect()``.
        """
        if store is None and db_path is not None:
            from backend.persistence.sqlite_adapter.store import SQLiteStore  # noqa: PLC0415

            store = SQLiteStore(f"sqlite:///{db_path}")
        self._store = store or get_store()
        if not hasattr(self._store, "connect"):
            raise TypeError("EnvironmentStore requires a durable store with connect()")

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

    def _scope(self, conn: Any, tenant_id: str) -> None:
        """Set the PostgreSQL tenant GUC for this transaction; a no-op on SQLite."""
        if self._is_postgres:
            set_postgres_tenant(conn, tenant_id)

    def _lock_tenant_for_write(self, conn: Any, tenant_id: str) -> None:
        """Serialize this transaction against other writers for the same tenant, on PostgreSQL.

        :meth:`create_environment`'s concurrency-limited path counts existing
        active rows for a tenant and then conditionally inserts a *new* row
        (E54-S2) -- ``SELECT ... FOR UPDATE`` cannot protect that shape,
        because it can only lock rows that already exist; a phantom row
        inserted by a concurrent transaction is invisible to it. SQLite's
        :func:`~backend.persistence.contract.begin_write` (``BEGIN
        IMMEDIATE``) already closes this gap with a whole-database write
        lock, so this is a no-op there. On PostgreSQL, a transaction-scoped
        advisory lock keyed by the tenant id (released automatically at
        commit or rollback -- never held past this transaction) gives every
        such writer for the same tenant the same serialization SQLite gets
        for free, mirroring
        :meth:`~backend.quotas.store.QuotaStore._lock_tenant_for_write`.

        Args:
            conn: Open connection with an in-progress write transaction.
            tenant_id: Tenant whose writers should be serialized against
                each other.
        """
        if self._is_postgres:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (tenant_id,))

    @staticmethod
    def _row_to_record(row: tuple) -> EnvironmentRecord:
        return EnvironmentRecord(
            environment_id=row[0],
            run_id=row[1],
            tenant_id=row[2],
            backend_kind=row[3],
            profile_id=row[4],
            profile_hash=row[5],
            workspace_path=row[6],
            status=row[7],
            created_at=row[8],
            expires_at=row[9],
            torn_down_at=row[10],
        )

    @staticmethod
    def _row_to_decision(row: tuple) -> EnvironmentDecisionRecord:
        return EnvironmentDecisionRecord(
            decision_id=row[0],
            environment_id=row[1],
            run_id=row[2],
            tenant_id=row[3],
            category=row[4],
            target=row[5],
            allowed=bool(row[6]),
            reason=row[7],
            decided_at=row[8],
        )

    # ------------------------------------------------------------- lifecycle

    def create_environment(
        self, record: EnvironmentRecord, *, max_concurrent: Optional[int] = None
    ) -> bool:
        """Durably persist a newly provisioned environment's record.

        Args:
            record: The environment record to insert.
            max_concurrent: When given, the insert is admitted only if the
                tenant's current active-environment count is below this
                ceiling. The count and the insert happen inside one
                transaction, serialized by :meth:`_lock_tenant_for_write`
                (E54-S2) -- a separate :meth:`count_active` call followed by
                this call would leave a race window across replicas/
                connections where both could observe the same
                under-the-limit count and both insert, overshooting it.
                ``None`` (the default) skips the check, inserting
                unconditionally.

        Returns:
            ``True`` if the record was inserted. ``False`` only when
            ``max_concurrent`` was given and the tenant was already at
            capacity -- the caller must not treat *record* as persisted and
            must release any real resource it already provisioned for this
            attempt.
        """
        with self._connect() as conn:
            self._scope(conn, record.tenant_id)
            self._begin_write(conn)
            self._lock_tenant_for_write(conn, record.tenant_id)
            if max_concurrent is not None:
                active = conn.execute(
                    self._sql(
                        "SELECT COUNT(*) FROM execution_environments "
                        "WHERE tenant_id = {p} AND status = 'active' AND expires_at > {p}"
                    ),
                    (record.tenant_id, _now()),
                ).fetchone()[0]
                if active >= max_concurrent:
                    conn.rollback()
                    return False
            conn.execute(
                self._sql(
                    "INSERT INTO execution_environments "
                    "(environment_id, run_id, tenant_id, backend_kind, profile_id, profile_hash, "
                    "workspace_path, status, created_at, expires_at, torn_down_at) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, NULL)"
                ),
                (
                    record.environment_id,
                    record.run_id,
                    record.tenant_id,
                    record.backend_kind,
                    record.profile_id,
                    record.profile_hash,
                    record.workspace_path,
                    record.status,
                    record.created_at,
                    record.expires_at,
                ),
            )
            conn.commit()
        return True

    def count_active(self, tenant_id: str) -> int:
        """Return the tenant's current active (non-expired, non-torn-down) environment count."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            row = conn.execute(
                self._sql(
                    "SELECT COUNT(*) FROM execution_environments "
                    "WHERE tenant_id = {p} AND status = 'active' AND expires_at > {p}"
                ),
                (tenant_id, _now()),
            ).fetchone()
        return int(row[0])

    def mark_status(
        self,
        environment_id: str,
        *,
        tenant_id: str,
        status: str,
        torn_down_at: Optional[str] = None,
    ) -> bool:
        """Update an environment record's lifecycle status; return whether a row changed.

        Idempotent (E54-S1-T3): once a record is in a terminal status
        (``"torn_down"`` or ``"orphaned"``), this is a no-op -- a retried
        teardown, or a reap raced by another replica that already claimed
        the same row, changes nothing and returns ``False`` rather than
        overwriting an already-recorded ``torn_down_at``.

        Args:
            environment_id: Environment to update.
            tenant_id: Tenant the environment belongs to (RLS scope on
                PostgreSQL).
            status: New status to record.
            torn_down_at: Teardown timestamp to record alongside a terminal
                status transition.

        Returns:
            Whether a row was actually changed.
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            terminal_placeholders = ", ".join(["{p}"] * len(_TERMINAL_STATUSES))
            cursor = conn.execute(
                self._sql(
                    "UPDATE execution_environments SET status = {p}, torn_down_at = {p} "
                    "WHERE environment_id = {p} AND tenant_id = {p} "
                    f"AND status NOT IN ({terminal_placeholders})"
                ),
                (status, torn_down_at, environment_id, tenant_id, *_TERMINAL_STATUSES),
            )
            conn.commit()
        return cursor.rowcount > 0

    def get(self, environment_id: str, *, tenant_id: str) -> Optional[EnvironmentRecord]:
        """Fetch one environment record by id, scoped to its owning tenant."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            row = conn.execute(
                self._sql(
                    f"SELECT {_ENV_COLUMNS} FROM execution_environments "
                    "WHERE environment_id = {p} AND tenant_id = {p}"
                ),
                (environment_id, tenant_id),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list_for_run(self, run_id: str, *, tenant_id: str) -> list[EnvironmentRecord]:
        """List every environment record provisioned for one run (audit, E32-S4-T1)."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            rows = conn.execute(
                self._sql(
                    f"SELECT {_ENV_COLUMNS} FROM execution_environments "
                    "WHERE run_id = {p} AND tenant_id = {p} ORDER BY created_at"
                ),
                (run_id, tenant_id),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_expired_active(self, tenant_id: str, *, before: str) -> list[EnvironmentRecord]:
        """List one tenant's active environments whose TTL has passed (orphan reaping, E32-S3-T1)."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            rows = conn.execute(
                self._sql(
                    f"SELECT {_ENV_COLUMNS} FROM execution_environments "
                    "WHERE tenant_id = {p} AND status = 'active' AND expires_at <= {p}"
                ),
                (tenant_id, before),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def claim_expired_active(self, tenant_id: str, *, before: str) -> list[EnvironmentRecord]:
        """Atomically claim every one tenant's active environments whose TTL has passed (E54-S3-T1).

        A single conditional ``UPDATE ... WHERE status = 'active' ...
        RETURNING`` transitions each matching row straight to ``"orphaned"``
        as part of selecting it -- there is no separate claim marker,
        because the status flip itself *is* the claim, and it reuses
        :meth:`mark_status`'s own terminal-status semantics (an environment
        already torn down or already claimed by another replica is not
        ``status = 'active'`` any more, so it simply will not match).

        This is what makes reaping safe to run on every replica
        simultaneously (E54-S3-T2): PostgreSQL re-evaluates an ``UPDATE``'s
        ``WHERE`` clause against each row's latest committed version before
        applying it, so two replicas racing the same sweep can never both
        claim the same row -- the loser's statement matches zero rows for
        it once the winner's transaction has committed. Crash recovery
        (E54-S3-T3) follows from the same property: an environment orphaned
        by a process that died mid-lifecycle stays ``status = 'active'``
        (nothing ever marked it otherwise) until its TTL passes, at which
        point *any* replica's next sweep -- not only the one that created
        it -- claims and tears it down.

        Args:
            tenant_id: Tenant to claim expired environments for.
            before: ISO-8601 cutoff; rows with ``expires_at`` at or before
                this are claimed.

        Returns:
            The claimed records, already reflecting the ``"orphaned"``
            status and this call's ``torn_down_at`` -- the caller now owns
            tearing down each one's real resources exactly once.
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            claimed_at = _now()
            rows = conn.execute(
                self._sql(
                    "UPDATE execution_environments SET status = 'orphaned', torn_down_at = {p} "
                    "WHERE tenant_id = {p} AND status = 'active' AND expires_at <= {p} "
                    f"RETURNING {_ENV_COLUMNS}"
                ),
                (claimed_at, tenant_id, before),
            ).fetchall()
            conn.commit()
        return [self._row_to_record(row) for row in rows]

    # ------------------------------------------------------------- decisions

    def record_decision(self, record: EnvironmentDecisionRecord) -> None:
        """Durably record one policy decision on a provisioned environment."""
        with self._connect() as conn:
            self._scope(conn, record.tenant_id)
            conn.execute(
                self._sql(
                    "INSERT INTO execution_environment_decisions "
                    "(decision_id, environment_id, run_id, tenant_id, category, target, allowed, "
                    "reason, decided_at) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"
                ),
                (
                    record.decision_id,
                    record.environment_id,
                    record.run_id,
                    record.tenant_id,
                    record.category,
                    record.target,
                    1 if record.allowed else 0,
                    record.reason,
                    record.decided_at,
                ),
            )
            conn.commit()

    def list_decisions_for_run(
        self, run_id: str, *, tenant_id: str
    ) -> list[EnvironmentDecisionRecord]:
        """List every policy decision recorded for one run's environments (audit)."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            rows = conn.execute(
                self._sql(
                    f"SELECT {_DECISION_COLUMNS} FROM execution_environment_decisions "
                    "WHERE run_id = {p} AND tenant_id = {p} ORDER BY decided_at"
                ),
                (run_id, tenant_id),
            ).fetchall()
        return [self._row_to_decision(row) for row in rows]


__all__ = ["EnvironmentDecisionRecord", "EnvironmentRecord", "EnvironmentStore"]
