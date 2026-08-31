"""Durable tenant quota policy, usage, lease, and reservation store (ADR-019).

Runs on both SQLite and PostgreSQL through the shared persistence contract
(E49, ADR-025; E51). Concurrent writers are serialized with the contract's
:func:`~backend.persistence.contract.begin_write` primitive -- ``BEGIN
IMMEDIATE`` on SQLite (a real file lock, safe across threads and processes on
one machine) and, on PostgreSQL, an explicit transaction whose critical reads
take :func:`~backend.persistence.contract.for_update_clause`'s row lock
(``SELECT ... FOR UPDATE``) instead of a database-wide lock. Every mutating
method commits exactly once, at the end of its own transaction.

All five tables carry Row-Level Security on PostgreSQL (E50-S4): every
tenant-scoped operation calls
:func:`~backend.persistence.tenancy.set_postgres_tenant` to set the
``app.tenant_id`` GUC inside the same transaction as its query, via
:meth:`QuotaStore._scope` (a no-op on SQLite, which has no RLS and is scoped
by the ``WHERE tenant_id = ...`` clauses already present in each query).

An optional Redis cache (wired in :mod:`backend.quotas.service`) never makes
an admission decision on its own -- this store is the sole authority for
every value it reads or writes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.persistence import contract
from backend.persistence.database import get_store
from backend.persistence.tenancy import set_postgres_tenant
from backend.quotas._time import iso as _iso
from backend.quotas._time import normalize as _normalize_timestamp
from backend.quotas._time import now_plus as _now_plus
from backend.quotas._time import parse_iso as _parse_iso
from backend.quotas.contracts import (
    LeaseResult,
    ReservationResult,
    TenantQuotaPolicy,
    UsageResult,
    policy_from_json,
    policy_to_json,
)


def _now() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


class QuotaStore:
    """Durable store for tenant quota policy, usage, leases, and reservations."""

    def __init__(self, db_path: Optional[Path] = None, *, store: Any = None) -> None:
        """Open the store against an explicit SQLite file, an injected store, or the configured one.

        Args:
            db_path: When given (and ``store`` is not), a SQLite file to open
                directly -- built into a dedicated
                :class:`~backend.persistence.sqlite_adapter.store.SQLiteStore`
                so tests can exercise real, independently-connected SQLite
                instances against the same file (e.g. a genuine multi-thread
                file-lock race).
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
            raise TypeError("QuotaStore requires a durable store with connect()")

    # --------------------------------------------------------------- helpers

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        return contract.is_postgres(getattr(self._store, "database_url", ""))

    def _sql(self, template: str) -> str:
        """Substitute this store's dialect placeholder/cast into a SQL template."""
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

    def _lock_tenant_for_write(self, conn: Any, tenant_id: str) -> None:
        """Serialize this transaction against other writers for the same tenant, on PostgreSQL.

        Some critical sections here count or sum existing rows for a tenant
        and then conditionally insert a *new* row (a fresh lease, a fresh
        reservation, a tenant's first policy) -- ``SELECT ... FOR UPDATE``
        cannot protect that shape, because it can only lock rows that
        already exist; a phantom row inserted by a concurrent transaction is
        invisible to it. SQLite's :func:`~backend.persistence.contract.begin_write`
        (``BEGIN IMMEDIATE``) already closes this gap with a whole-database
        write lock, so this is a no-op there. On PostgreSQL, a
        transaction-scoped advisory lock keyed by the tenant id (released
        automatically at commit or rollback -- never held past this
        transaction) gives every such writer for the same tenant the same
        serialization SQLite gets for free.

        Args:
            conn: Open connection with an in-progress write transaction.
            tenant_id: Tenant whose writers should be serialized against
                each other.
        """
        if self._is_postgres:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (tenant_id,))

    # ------------------------------------------------------------ policy

    def list_tenant_ids(self) -> list[str]:
        """Return every tenant with a durably stored quota policy.

        Local-mode tenants relying on finite defaults (never explicitly
        configured) are not included -- there is nothing durable to list
        for them.

        On PostgreSQL, this intentionally does not set the ``app.tenant_id``
        GUC (there is no single tenant to scope to for a cross-tenant
        listing): with Row-Level Security forced, the result reflects
        whatever the connection's ambient tenant scope already is, which is
        empty for an unscoped connection. Cross-tenant enumeration for
        operator tooling is out of this epic's scope (it requires a
        superuser/``BYPASSRLS`` administrative path, not a persistence-port
        concern).

        Returns:
            Tenant ids, in no particular order.
        """
        with self._connect() as conn:
            rows = conn.execute(
                self._sql("SELECT tenant_id FROM tenant_quota_policies")
            ).fetchall()
        return [row[0] for row in rows]

    def get_policy(self, tenant_id: str) -> Optional[TenantQuotaPolicy]:
        """Fetch a tenant's durable quota policy, or ``None`` if unconfigured."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            row = conn.execute(
                self._sql(
                    "SELECT policy_json, version FROM tenant_quota_policies WHERE tenant_id = {p}"
                ),
                (tenant_id,),
            ).fetchone()
        if row is None:
            return None
        return policy_from_json(tenant_id, row[0], row[1])

    def upsert_policy(
        self, policy: TenantQuotaPolicy, *, expected_version: Optional[int] = None
    ) -> TenantQuotaPolicy:
        """Create or replace a tenant's policy, optimistically concurrency-checked.

        Args:
            policy: The new policy to store (its own ``version`` is ignored;
                the stored version always increments by one).
            expected_version: When given, the write is rejected unless the
                currently stored version matches exactly (compare-and-swap).
                ``None`` bypasses the check (first-write or admin override).

        Returns:
            The stored policy, with its incremented version.

        Raises:
            ValueError: If ``expected_version`` does not match the current
                stored version.
        """
        with self._connect() as conn:
            self._scope(conn, policy.tenant_id)
            self._begin_write(conn)
            self._lock_tenant_for_write(conn, policy.tenant_id)
            row = conn.execute(
                self._sql(
                    "SELECT version FROM tenant_quota_policies WHERE tenant_id = {p}"
                    + self._for_update()
                ),
                (policy.tenant_id,),
            ).fetchone()
            current_version = row[0] if row is not None else 0
            if expected_version is not None and expected_version != current_version:
                conn.rollback()
                raise ValueError(
                    f"expected_version {expected_version} does not match stored "
                    f"version {current_version} for tenant {policy.tenant_id!r}"
                )
            next_version = current_version + 1
            conn.execute(
                self._sql(
                    """
                    INSERT INTO tenant_quota_policies (tenant_id, policy_json, version, updated_at)
                    VALUES ({p}, {p}{jsonb}, {p}, {p})
                    ON CONFLICT (tenant_id) DO UPDATE SET
                        policy_json = excluded.policy_json,
                        version = excluded.version,
                        updated_at = excluded.updated_at
                    """
                ),
                (policy.tenant_id, policy_to_json(policy), next_version, _now()),
            )
            conn.commit()
        stored = self.get_policy(policy.tenant_id)
        assert stored is not None
        return stored

    # -------------------------------------------------------- run leases

    def acquire_run_lease(
        self, *, tenant_id: str, run_id: str, max_concurrent_runs: int, lease_seconds: int
    ) -> LeaseResult:
        """Atomically acquire (or idempotently resume) one concurrency lease.

        A lease already held for ``run_id`` is reused without consuming a
        new concurrency slot (idempotent resume/retry). A lease that expired
        without a heartbeat is reclaimed by the next caller, whoever it is.

        Args:
            tenant_id: Tenant the run belongs to.
            run_id: Unique identifier of the run requesting admission.
            max_concurrent_runs: The tenant's configured concurrency limit.
            lease_seconds: How long the lease is valid without a heartbeat.

        Returns:
            The acquisition outcome.
        """
        now = time.time()
        expires_at = _now_plus(lease_seconds)
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            self._lock_tenant_for_write(conn, tenant_id)
            existing = conn.execute(
                self._sql(
                    "SELECT expires_at, released_at FROM run_leases WHERE run_id = {p}"
                    + self._for_update()
                ),
                (run_id,),
            ).fetchone()
            if existing is not None and existing[1] is None and (
                _parse_iso(existing[0]) > now
            ):
                conn.commit()
                return LeaseResult(
                    granted=True, resumed=True, expires_at=_normalize_timestamp(existing[0])
                )

            active = conn.execute(
                self._sql(
                    "SELECT COUNT(*) FROM run_leases WHERE tenant_id = {p} "
                    "AND released_at IS NULL AND run_id != {p} AND expires_at > {p}"
                ),
                (tenant_id, run_id, _iso(now)),
            ).fetchone()[0]
            if active >= max_concurrent_runs:
                conn.rollback()
                return LeaseResult(granted=False, resumed=False, expires_at=None)

            conn.execute(
                self._sql(
                    """
                    INSERT INTO run_leases (run_id, tenant_id, acquired_at, expires_at, released_at)
                    VALUES ({p}, {p}, {p}, {p}, NULL)
                    ON CONFLICT (run_id) DO UPDATE SET
                        tenant_id = excluded.tenant_id,
                        acquired_at = excluded.acquired_at,
                        expires_at = excluded.expires_at,
                        released_at = NULL
                    """
                ),
                (run_id, tenant_id, _iso(now), expires_at),
            )
            conn.commit()
            return LeaseResult(granted=True, resumed=False, expires_at=expires_at)

    def heartbeat_run_lease(self, *, tenant_id: str, run_id: str, lease_seconds: int) -> bool:
        """Extend an active lease's expiry; a no-op if already released/expired.

        Args:
            tenant_id: Tenant the lease belongs to.
            run_id: Run whose lease should be extended.
            lease_seconds: New validity window from now.

        Returns:
            ``True`` if an active lease was extended.
        """
        expires_at = _now_plus(lease_seconds)
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            cursor = conn.execute(
                self._sql(
                    "UPDATE run_leases SET expires_at = {p} "
                    "WHERE run_id = {p} AND released_at IS NULL"
                ),
                (expires_at, run_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def release_run_lease(self, *, tenant_id: str, run_id: str) -> None:
        """Release a run's concurrency lease, freeing its tenant's slot."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            conn.execute(
                self._sql(
                    "UPDATE run_leases SET released_at = {p} WHERE run_id = {p} AND released_at IS NULL"
                ),
                (_now(), run_id),
            )
            conn.commit()

    def count_active_leases(self, tenant_id: str) -> int:
        """Return the tenant's current active (non-expired, non-released) lease count."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            row = conn.execute(
                self._sql(
                    "SELECT COUNT(*) FROM run_leases WHERE tenant_id = {p} "
                    "AND released_at IS NULL AND expires_at > {p}"
                ),
                (tenant_id, _now()),
            ).fetchone()
        return int(row[0])

    # --------------------------------------------------- storage reserve

    def reserve_storage(
        self, *, tenant_id: str, bytes_requested: int, idempotency_key: str, max_storage_bytes: int
    ) -> ReservationResult:
        """Atomically reserve storage bytes against a tenant's byte ceiling.

        Args:
            tenant_id: Tenant the reservation belongs to.
            bytes_requested: Bytes to reserve.
            idempotency_key: Caller-supplied key; a retry with the same key
                returns the original outcome rather than double-reserving.
            max_storage_bytes: The tenant's configured storage ceiling.

        Returns:
            The reservation outcome.
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            self._lock_tenant_for_write(conn, tenant_id)
            existing = conn.execute(
                self._sql(
                    "SELECT status FROM storage_reservations WHERE reservation_id = {p}"
                    + self._for_update()
                ),
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                conn.commit()
                granted = existing[0] != "denied"
                return ReservationResult(
                    granted=granted, reservation_id=idempotency_key if granted else None
                )

            held = conn.execute(
                self._sql(
                    "SELECT COALESCE(SUM(bytes), 0) FROM storage_reservations "
                    "WHERE tenant_id = {p} AND status IN ('reserved', 'committed')"
                ),
                (tenant_id,),
            ).fetchone()[0]
            if held + bytes_requested > max_storage_bytes:
                conn.execute(
                    self._sql(
                        "INSERT INTO storage_reservations "
                        "(reservation_id, tenant_id, bytes, status, created_at) "
                        "VALUES ({p}, {p}, {p}, 'denied', {p})"
                    ),
                    (idempotency_key, tenant_id, bytes_requested, _now()),
                )
                conn.commit()
                return ReservationResult(granted=False, reservation_id=None)

            conn.execute(
                self._sql(
                    "INSERT INTO storage_reservations "
                    "(reservation_id, tenant_id, bytes, status, created_at) "
                    "VALUES ({p}, {p}, {p}, 'reserved', {p})"
                ),
                (idempotency_key, tenant_id, bytes_requested, _now()),
            )
            conn.commit()
            return ReservationResult(granted=True, reservation_id=idempotency_key)

    def commit_storage_reservation(
        self, *, tenant_id: str, reservation_id: str, actual_bytes: int
    ) -> None:
        """Settle a reservation to its actual byte size on a successful write.

        A single atomic conditional ``UPDATE`` guarded by ``status =
        'reserved'``: a reservation already committed (or released) matches
        no row, so a retried or duplicate commit is a safe no-op rather than
        a double-commit.
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            conn.execute(
                self._sql(
                    "UPDATE storage_reservations SET status = 'committed', bytes = {p} "
                    "WHERE reservation_id = {p} AND status = 'reserved'"
                ),
                (actual_bytes, reservation_id),
            )
            conn.commit()

    def release_storage_reservation(self, *, tenant_id: str, reservation_id: str) -> None:
        """Release a reservation that will never be committed (failed write).

        Guarded the same way as :meth:`commit_storage_reservation`: only a
        still-``reserved`` row is affected, so a duplicate release cannot
        double-refund capacity already committed or already released.
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            conn.execute(
                self._sql(
                    "UPDATE storage_reservations SET status = 'released' "
                    "WHERE reservation_id = {p} AND status = 'reserved'"
                ),
                (reservation_id,),
            )
            conn.commit()

    def storage_used(self, tenant_id: str) -> int:
        """Return a tenant's currently held (reserved + committed) storage bytes."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            row = conn.execute(
                self._sql(
                    "SELECT COALESCE(SUM(bytes), 0) FROM storage_reservations "
                    "WHERE tenant_id = {p} AND status IN ('reserved', 'committed')"
                ),
                (tenant_id,),
            ).fetchone()
        return int(row[0])

    # ------------------------------------------------------- rate limit

    def consume_request_slot(
        self, *, tenant_id: str, credential_id: str, requests_per_second: int
    ) -> bool:
        """Atomically consume one request slot in the current one-second window.

        Args:
            tenant_id: Tenant the presented credential belongs to.
            credential_id: The presented credential's stable identifier.
            requests_per_second: The credential's configured rate limit.

        Returns:
            ``True`` if the request is admitted; ``False`` if the window is
            already at its limit.
        """
        window_start = int(time.time())
        conflict_columns = (
            "(tenant_id, credential_id, window_start)"
            if self._is_postgres
            else "(credential_id, window_start)"
        )
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO request_rate_buckets (tenant_id, credential_id, window_start, count) "
                    "VALUES ({p}, {p}, {p}, 0) ON CONFLICT " + conflict_columns + " DO NOTHING"
                ),
                (tenant_id, credential_id, window_start),
            )
            cursor = conn.execute(
                self._sql(
                    "UPDATE request_rate_buckets SET count = count + 1 "
                    "WHERE tenant_id = {p} AND credential_id = {p} AND window_start = {p} "
                    "AND count < {p}"
                ),
                (tenant_id, credential_id, window_start, requests_per_second),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------ monthly usage

    def record_monthly_usage(
        self,
        *,
        tenant_id: str,
        resource: str,
        delta: int,
        window_key: str,
        limit: int,
        warning_ratio_basis_points: int,
    ) -> UsageResult:
        """Atomically add ``delta`` to a tenant's usage for one resource/window.

        Denies (without recording) when the addition would exceed ``limit``,
        via a single conditional ``UPDATE`` (``used + delta <= limit`` in its
        ``WHERE`` clause) rather than a separate read-then-decide-then-write
        -- the row's own atomicity is what prevents overshoot under
        concurrent callers, not the surrounding transaction alone. Reports
        (without persisting a second flag) the first call whose delta
        crosses the configured warning ratio for this tenant/resource/window,
        derived from the pre- and post-update ``used`` values the same
        statement already produces.

        Args:
            tenant_id: Tenant whose usage is being recorded.
            resource: Stable resource dimension name (e.g. ``"monthly_tokens"``).
            delta: Amount to add; must be non-negative.
            window_key: Stable key identifying the current window (e.g. the
                UTC month's ISO start date) — a new key resets the counter.
            limit: The configured limit for this resource.
            warning_ratio_basis_points: Ratio (out of 10,000) at which the
                first crossing is reported via ``crossed_warning``.

        Returns:
            The recording outcome.
        """
        threshold = limit * warning_ratio_basis_points
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO tenant_usage_windows "
                    "(tenant_id, resource, window_key, used, warned) VALUES ({p}, {p}, {p}, 0, 0) "
                    "ON CONFLICT (tenant_id, resource, window_key) DO NOTHING"
                ),
                (tenant_id, resource, window_key),
            )
            row = conn.execute(
                self._sql(
                    "UPDATE tenant_usage_windows SET "
                    "used = used + {p}, "
                    "warned = CASE WHEN warned = 1 THEN 1 "
                    "WHEN (used + {p}) * 10000 >= {p} THEN 1 ELSE 0 END "
                    "WHERE tenant_id = {p} AND resource = {p} AND window_key = {p} "
                    "AND used + {p} <= {p} "
                    "RETURNING used"
                ),
                (delta, delta, threshold, tenant_id, resource, window_key, delta, limit),
            ).fetchone()
            if row is None:
                current = conn.execute(
                    self._sql(
                        "SELECT used FROM tenant_usage_windows "
                        "WHERE tenant_id = {p} AND resource = {p} AND window_key = {p}"
                    ),
                    (tenant_id, resource, window_key),
                ).fetchone()[0]
                conn.commit()
                return UsageResult(
                    granted=False, used=int(current), limit=limit, crossed_warning=False
                )
            new_used = int(row[0])
            old_used = new_used - delta
            crossed_warning = old_used * 10_000 < threshold <= new_used * 10_000
            conn.commit()
            return UsageResult(
                granted=True, used=new_used, limit=limit, crossed_warning=crossed_warning
            )

    def usage_snapshot(self, tenant_id: str, resource: str, window_key: str) -> int:
        """Return a tenant's currently recorded usage for one resource/window."""
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            row = conn.execute(
                self._sql(
                    "SELECT used FROM tenant_usage_windows "
                    "WHERE tenant_id = {p} AND resource = {p} AND window_key = {p}"
                ),
                (tenant_id, resource, window_key),
            ).fetchone()
        return int(row[0]) if row is not None else 0


__all__ = [
    "LeaseResult",
    "QuotaStore",
    "ReservationResult",
    "UsageResult",
]
