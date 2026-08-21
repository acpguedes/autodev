"""Postgres EvalResultRepository and ScoreSnapshotRepository implementations."""

from __future__ import annotations

from typing import Any

from backend.persistence.codecs import build_promotion_record, dumps_json, loads_json
from backend.persistence.postgres_adapter._shared import _ConnectionOwner
from backend.persistence.tenancy import DEFAULT_TENANT_ID, set_postgres_tenant


class _EvalScoringMixin(_ConnectionOwner):
    """``eval_results``, ``score_snapshots``, and ``score_snapshot_promotions`` read/write (E5-S3, E5-S4)."""

    def create_eval_result(
        self,
        *,
        eval_id: str,
        eval_version: str,
        run_id: str,
        document: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Persist one eval result document, scoped to *tenant_id*. Never overwrites an existing run (E5-S3)."""
        gate_passed = bool((document.get("gate") or {}).get("passed", True))
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                """
                INSERT INTO eval_results (eval_id, eval_version, run_id, mode, gate_passed, document_json, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    eval_id,
                    eval_version,
                    run_id,
                    str(document.get("mode", "offline")),
                    gate_passed,
                    dumps_json(document),
                    tenant_id,
                ),
            )
            conn.commit()

    def get_eval_result(
        self, eval_id: str, eval_version: str, run_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, Any] | None:
        """Fetch one eval result document, or ``None`` if it does not exist (E5-S3), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                "SELECT document_json FROM eval_results WHERE eval_id = %s AND eval_version = %s AND run_id = %s",
                (eval_id, eval_version, run_id),
            ).fetchone()
        return loads_json(row[0]) if row is not None else None

    def list_eval_results(
        self, eval_id: str, eval_version: str | None = None, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List eval result documents for an id, newest first, optionally by version (E5-S3), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            if eval_version is not None:
                rows = conn.execute(
                    "SELECT document_json FROM eval_results WHERE eval_id = %s AND eval_version = %s "
                    "ORDER BY id DESC",
                    (eval_id, eval_version),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT document_json FROM eval_results WHERE eval_id = %s ORDER BY id DESC",
                    (eval_id,),
                ).fetchall()
        return [loads_json(row[0]) for row in rows]

    def create_score_snapshot(
        self,
        *,
        snapshot_id: str,
        sample_count: int,
        document: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Persist one immutable, versioned score snapshot document (E5-S4), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                "INSERT INTO score_snapshots (snapshot_id, sample_count, document_json, tenant_id) "
                "VALUES (%s, %s, %s::jsonb, %s)",
                (snapshot_id, sample_count, dumps_json(document), tenant_id),
            )
            conn.commit()

    def get_score_snapshot(self, snapshot_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any] | None:
        """Fetch one persisted score snapshot document, or ``None`` (E5-S4), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                "SELECT document_json FROM score_snapshots WHERE snapshot_id = %s", (snapshot_id,)
            ).fetchone()
        return loads_json(row[0]) if row is not None else None

    def list_score_snapshots(self, limit: int = 50, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List persisted score snapshots, newest first (E5-S4), scoped to *tenant_id*."""
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                "SELECT document_json FROM score_snapshots ORDER BY id DESC LIMIT %s", (limit,)
            ).fetchall()
        return [loads_json(row[0]) for row in rows]

    def record_snapshot_promotion(
        self,
        *,
        policy_id: str,
        snapshot_id: str,
        baseline_snapshot_id: str,
        promoted: bool,
        reason: str,
        decided_at: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Append one promotion decision (promoted or blocked) to the audit log (E5-S4).

        ``score_snapshot_promotions`` has no ``tenant_id`` column or RLS
        policy of its own (ADR-010: scoped transitively through its parent
        ``score_snapshots`` row via *snapshot_id*), so this insert is not
        itself RLS-checked. *tenant_id* still scopes the transaction (via
        :func:`~backend.persistence.tenancy.set_postgres_tenant`) for
        consistency with every other method and any future reads sharing
        this connection.
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            conn.execute(
                "INSERT INTO score_snapshot_promotions "
                "(policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at),
            )
            conn.commit()

    def get_active_score_snapshot(self, policy_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any] | None:
        """Fetch the currently promoted snapshot document for a policy id (E5-S4), scoped to *tenant_id*.

        Joins to ``score_snapshots`` so RLS on that table (which does carry
        a ``tenant_id`` column and policy) transitively filters out
        promotions pointing at a snapshot outside *tenant_id*'s scope.
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            row = conn.execute(
                """
                SELECT ssp.snapshot_id
                FROM score_snapshot_promotions ssp
                JOIN score_snapshots ss ON ss.snapshot_id = ssp.snapshot_id
                WHERE ssp.policy_id = %s AND ssp.promoted = TRUE
                ORDER BY ssp.id DESC LIMIT 1
                """,
                (policy_id,),
            ).fetchone()
        if row is None:
            return None
        return self.get_score_snapshot(row[0], tenant_id=tenant_id)

    def list_snapshot_promotions(self, policy_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
        """List every promotion decision recorded for a policy id, newest first (E5-S4), scoped to *tenant_id*.

        See :meth:`get_active_score_snapshot` for why this joins to
        ``score_snapshots``.
        """
        with self.connect() as conn:
            set_postgres_tenant(conn, tenant_id)
            rows = conn.execute(
                """
                SELECT ssp.policy_id, ssp.snapshot_id, ssp.baseline_snapshot_id, ssp.promoted, ssp.reason,
                       ssp.decided_at
                FROM score_snapshot_promotions ssp
                JOIN score_snapshots ss ON ss.snapshot_id = ssp.snapshot_id
                WHERE ssp.policy_id = %s ORDER BY ssp.id DESC
                """,
                (policy_id,),
            ).fetchall()
        return [
            build_promotion_record(
                policy_id=row[0],
                snapshot_id=row[1],
                baseline_snapshot_id=row[2],
                promoted=row[3],
                reason=row[4],
                decided_at=row[5],
            )
            for row in rows
        ]


__all__ = ["_EvalScoringMixin"]
