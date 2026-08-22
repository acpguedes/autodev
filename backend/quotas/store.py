"""Durable tenant quota policy, usage, lease, and reservation store (ADR-019).

SQLite is the sole implementation today (E49-S2, ADR-025): this store only
accepts a ``sqlite://`` ``DATABASE_URL`` and predates the shared persistence
contract, so it is not yet constructible against PostgreSQL at all. An
optional Redis cache (wired in :mod:`backend.quotas.service`) never makes an
admission decision on its own — SQLite is the sole authority for every value
this module reads or writes. Concurrent writers are serialized with ``BEGIN
IMMEDIATE`` (a real file-lock, safe across threads and processes on one
machine); every mutating method commits exactly once, at the end of its own
transaction.

Porting this store onto PostgreSQL is E51, which will serialize the
equivalent critical sections with an explicit transaction plus ``SELECT ...
FOR UPDATE`` — the row-lock primitive already exists for that port at
:func:`backend.persistence.contract.for_update_clause`, alongside
:func:`backend.persistence.contract.begin_write` for the SQLite side of the
same operation.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.quotas._time import iso as _iso
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

_DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"


def _now() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path(database_url: str) -> Path:
    """Resolve a ``sqlite://`` URL to a filesystem path, matching the core stores."""
    url = (database_url or _DEFAULT_DATABASE_URL).strip()
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
    elif url.startswith("sqlite://"):
        raw = url.removeprefix("sqlite://")
    else:
        raise ValueError(f"QuotaStore requires a sqlite:// DATABASE_URL. Got: {url!r}")
    return Path(raw).expanduser().resolve()


class QuotaStore:
    """SQLite-backed durable store for tenant quota policy, usage, and leases."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Open (creating if needed) the SQLite-backed quota tables.

        Args:
            db_path: Explicit database file path; defaults to resolving
                ``DATABASE_URL``.
        """
        self._db_path = db_path or _resolve_db_path(os.environ.get("DATABASE_URL", ""))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._create_schema(conn)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenant_quota_policies (
                tenant_id TEXT PRIMARY KEY,
                policy_json TEXT NOT NULL,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tenant_usage_windows (
                tenant_id TEXT NOT NULL,
                resource TEXT NOT NULL,
                window_key TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                warned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (tenant_id, resource, window_key)
            );
            CREATE TABLE IF NOT EXISTS run_leases (
                run_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                released_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_run_leases_tenant
                ON run_leases(tenant_id, released_at, expires_at);
            CREATE TABLE IF NOT EXISTS storage_reservations (
                reservation_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_storage_reservations_tenant
                ON storage_reservations(tenant_id, status);
            CREATE TABLE IF NOT EXISTS request_rate_buckets (
                credential_id TEXT NOT NULL,
                window_start INTEGER NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (credential_id, window_start)
            );
            """
        )

    # ------------------------------------------------------------ policy

    def list_tenant_ids(self) -> list[str]:
        """Return every tenant with a durably stored quota policy.

        Local-mode tenants relying on finite defaults (never explicitly
        configured) are not included -- there is nothing durable to list
        for them.

        Returns:
            Tenant ids, in no particular order.
        """
        with self._connect() as conn:
            rows = conn.execute("SELECT tenant_id FROM tenant_quota_policies").fetchall()
        return [row["tenant_id"] for row in rows]

    def get_policy(self, tenant_id: str) -> Optional[TenantQuotaPolicy]:
        """Fetch a tenant's durable quota policy, or ``None`` if unconfigured."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT policy_json, version FROM tenant_quota_policies WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
        if row is None:
            return None
        return policy_from_json(tenant_id, row["policy_json"], row["version"])

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
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT version FROM tenant_quota_policies WHERE tenant_id = ?",
                (policy.tenant_id,),
            ).fetchone()
            current_version = row["version"] if row is not None else 0
            if expected_version is not None and expected_version != current_version:
                conn.rollback()
                raise ValueError(
                    f"expected_version {expected_version} does not match stored "
                    f"version {current_version} for tenant {policy.tenant_id!r}"
                )
            next_version = current_version + 1
            conn.execute(
                """
                INSERT INTO tenant_quota_policies (tenant_id, policy_json, version, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    policy_json = excluded.policy_json,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
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
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT expires_at, released_at FROM run_leases WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if existing is not None and existing["released_at"] is None and (
                _parse_iso(existing["expires_at"]) > now
            ):
                conn.commit()
                return LeaseResult(granted=True, resumed=True, expires_at=existing["expires_at"])

            active = conn.execute(
                "SELECT COUNT(*) AS n FROM run_leases WHERE tenant_id = ? "
                "AND released_at IS NULL AND run_id != ? AND expires_at > ?",
                (tenant_id, run_id, _iso(now)),
            ).fetchone()["n"]
            if active >= max_concurrent_runs:
                conn.rollback()
                return LeaseResult(granted=False, resumed=False, expires_at=None)

            conn.execute(
                """
                INSERT INTO run_leases (run_id, tenant_id, acquired_at, expires_at, released_at)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(run_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at,
                    released_at = NULL
                """,
                (run_id, tenant_id, _iso(now), expires_at),
            )
            conn.commit()
            return LeaseResult(granted=True, resumed=False, expires_at=expires_at)

    def heartbeat_run_lease(self, run_id: str, *, lease_seconds: int) -> bool:
        """Extend an active lease's expiry; a no-op if already released/expired.

        Args:
            run_id: Run whose lease should be extended.
            lease_seconds: New validity window from now.

        Returns:
            ``True`` if an active lease was extended.
        """
        expires_at = _now_plus(lease_seconds)
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE run_leases SET expires_at = ? "
                "WHERE run_id = ? AND released_at IS NULL",
                (expires_at, run_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def release_run_lease(self, run_id: str) -> None:
        """Release a run's concurrency lease, freeing its tenant's slot."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE run_leases SET released_at = ? WHERE run_id = ? AND released_at IS NULL",
                (_now(), run_id),
            )
            conn.commit()

    def count_active_leases(self, tenant_id: str) -> int:
        """Return the tenant's current active (non-expired, non-released) lease count."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM run_leases WHERE tenant_id = ? "
                "AND released_at IS NULL AND expires_at > ?",
                (tenant_id, _now()),
            ).fetchone()
        return int(row["n"])

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
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT status FROM storage_reservations WHERE reservation_id = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                conn.commit()
                granted = existing["status"] != "denied"
                return ReservationResult(
                    granted=granted, reservation_id=idempotency_key if granted else None
                )

            held = conn.execute(
                "SELECT COALESCE(SUM(bytes), 0) AS total FROM storage_reservations "
                "WHERE tenant_id = ? AND status IN ('reserved', 'committed')",
                (tenant_id,),
            ).fetchone()["total"]
            if held + bytes_requested > max_storage_bytes:
                conn.execute(
                    "INSERT INTO storage_reservations "
                    "(reservation_id, tenant_id, bytes, status, created_at) VALUES (?, ?, ?, 'denied', ?)",
                    (idempotency_key, tenant_id, bytes_requested, _now()),
                )
                conn.commit()
                return ReservationResult(granted=False, reservation_id=None)

            conn.execute(
                "INSERT INTO storage_reservations "
                "(reservation_id, tenant_id, bytes, status, created_at) VALUES (?, ?, ?, 'reserved', ?)",
                (idempotency_key, tenant_id, bytes_requested, _now()),
            )
            conn.commit()
            return ReservationResult(granted=True, reservation_id=idempotency_key)

    def commit_storage_reservation(self, reservation_id: str, *, actual_bytes: int) -> None:
        """Settle a reservation to its actual byte size on a successful write."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE storage_reservations SET status = 'committed', bytes = ? "
                "WHERE reservation_id = ? AND status = 'reserved'",
                (actual_bytes, reservation_id),
            )
            conn.commit()

    def release_storage_reservation(self, reservation_id: str) -> None:
        """Release a reservation that will never be committed (failed write)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE storage_reservations SET status = 'released' "
                "WHERE reservation_id = ? AND status = 'reserved'",
                (reservation_id,),
            )
            conn.commit()

    def storage_used(self, tenant_id: str) -> int:
        """Return a tenant's currently held (reserved + committed) storage bytes."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(bytes), 0) AS total FROM storage_reservations "
                "WHERE tenant_id = ? AND status IN ('reserved', 'committed')",
                (tenant_id,),
            ).fetchone()
        return int(row["total"])

    # ------------------------------------------------------- rate limit

    def consume_request_slot(self, *, credential_id: str, requests_per_second: int) -> bool:
        """Atomically consume one request slot in the current one-second window.

        Args:
            credential_id: The presented credential's stable identifier.
            requests_per_second: The credential's configured rate limit.

        Returns:
            ``True`` if the request is admitted; ``False`` if the window is
            already at its limit.
        """
        window_start = int(time.time())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO request_rate_buckets (credential_id, window_start, count) "
                "VALUES (?, ?, 0)",
                (credential_id, window_start),
            )
            cursor = conn.execute(
                "UPDATE request_rate_buckets SET count = count + 1 "
                "WHERE credential_id = ? AND window_start = ? AND count < ?",
                (credential_id, window_start, requests_per_second),
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

        Denies (without recording) when the addition would exceed ``limit``.
        Marks (once, durably) the first call that crosses the configured
        warning ratio for this tenant/resource/window.

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
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO tenant_usage_windows "
                "(tenant_id, resource, window_key, used, warned) VALUES (?, ?, ?, 0, 0)",
                (tenant_id, resource, window_key),
            )
            row = conn.execute(
                "SELECT used, warned FROM tenant_usage_windows "
                "WHERE tenant_id = ? AND resource = ? AND window_key = ?",
                (tenant_id, resource, window_key),
            ).fetchone()
            current = row["used"]
            if current + delta > limit:
                conn.rollback()
                return UsageResult(granted=False, used=current, limit=limit, crossed_warning=False)

            new_used = current + delta
            crossed_warning = (
                row["warned"] == 0 and new_used * 10_000 >= limit * warning_ratio_basis_points
            )
            conn.execute(
                "UPDATE tenant_usage_windows SET used = ?, warned = ? "
                "WHERE tenant_id = ? AND resource = ? AND window_key = ?",
                (new_used, 1 if crossed_warning else row["warned"], tenant_id, resource, window_key),
            )
            conn.commit()
            return UsageResult(
                granted=True, used=new_used, limit=limit, crossed_warning=crossed_warning
            )

    def usage_snapshot(self, tenant_id: str, resource: str, window_key: str) -> int:
        """Return a tenant's currently recorded usage for one resource/window."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT used FROM tenant_usage_windows "
                "WHERE tenant_id = ? AND resource = ? AND window_key = ?",
                (tenant_id, resource, window_key),
            ).fetchone()
        return int(row["used"]) if row is not None else 0


__all__ = [
    "LeaseResult",
    "QuotaStore",
    "ReservationResult",
    "UsageResult",
]
