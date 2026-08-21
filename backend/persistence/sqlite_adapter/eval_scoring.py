"""SQLite EvalResultRepository and ScoreSnapshotRepository implementations."""

from __future__ import annotations

from typing import Any

from backend.persistence.codecs import build_promotion_record, dumps_json, loads_json
from backend.persistence.sqlite_adapter._shared import _ConnectionOwner
from backend.persistence.tenancy import DEFAULT_TENANT_ID, sqlite_tenant_clause


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
        """Persist one eval result document scoped to *tenant_id* (E5-S3)."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO eval_results (eval_id, eval_version, run_id, mode, gate_passed, "
                "document_json, tenant_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    eval_id,
                    eval_version,
                    run_id,
                    str(document.get("mode", "offline")),
                    1 if (document.get("gate") or {}).get("passed", True) else 0,
                    dumps_json(document),
                    tenant_id,
                ),
            )
            conn.commit()

    def get_eval_result(
        self,
        eval_id: str,
        eval_version: str,
        run_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> dict[str, Any] | None:
        """Fetch one eval result document scoped to *tenant_id* (E5-S3)."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT document_json FROM eval_results WHERE eval_id = ? AND eval_version = ? "
                f"AND run_id = ? {clause}",
                (eval_id, eval_version, run_id, *params),
            ).fetchone()
        return loads_json(row["document_json"]) if row is not None else None

    def list_eval_results(
        self,
        eval_id: str,
        eval_version: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict[str, Any]]:
        """List eval result documents for an id scoped to *tenant_id*, newest first (E5-S3)."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            if eval_version is not None:
                rows = conn.execute(
                    f"SELECT document_json FROM eval_results WHERE eval_id = ? AND eval_version = ? "
                    f"{clause} ORDER BY id DESC",
                    (eval_id, eval_version, *params),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT document_json FROM eval_results WHERE eval_id = ? {clause} ORDER BY id DESC",
                    (eval_id, *params),
                ).fetchall()
        return [loads_json(row["document_json"]) for row in rows]

    def create_score_snapshot(
        self,
        *,
        snapshot_id: str,
        sample_count: int,
        document: dict[str, Any],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Persist one immutable, versioned score snapshot document scoped to *tenant_id* (E5-S4)."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO score_snapshots (snapshot_id, sample_count, document_json, tenant_id) "
                "VALUES (?, ?, ?, ?)",
                (snapshot_id, sample_count, dumps_json(document), tenant_id),
            )
            conn.commit()

    def get_score_snapshot(
        self, snapshot_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, Any] | None:
        """Fetch one persisted score snapshot document scoped to *tenant_id*, or ``None`` (E5-S4)."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT document_json FROM score_snapshots WHERE snapshot_id = ? {clause}",
                (snapshot_id, *params),
            ).fetchone()
        return loads_json(row["document_json"]) if row is not None else None

    def list_score_snapshots(
        self, limit: int = 50, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List persisted score snapshots scoped to *tenant_id*, newest first (E5-S4)."""
        clause, params = sqlite_tenant_clause(tenant_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT document_json FROM score_snapshots WHERE 1=1 {clause} "
                f"ORDER BY id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [loads_json(row["document_json"]) for row in rows]

    def record_snapshot_promotion(
        self,
        *,
        policy_id: str,
        snapshot_id: str,
        baseline_snapshot_id: str,
        promoted: bool,
        reason: str,
        decided_at: str,
        tenant_id: str = DEFAULT_TENANT_ID,  # noqa: ARG002 - see docstring
    ) -> None:
        """Append one promotion decision (promoted or blocked) to the audit log (E5-S4).

        ``score_snapshot_promotions`` has no ``tenant_id`` column of its own
        by design (ADR-010): it is scoped transitively through the referenced
        snapshot's tenant via ``snapshot_id`` (see
        :meth:`get_active_score_snapshot` and :meth:`list_snapshot_promotions`).
        *tenant_id* is accepted for interface parity with
        :class:`~backend.persistence.base.ScoreSnapshotRepository` but is not
        stored as a column on this audit-log table.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO score_snapshot_promotions "
                "(policy_id, snapshot_id, baseline_snapshot_id, promoted, reason, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (policy_id, snapshot_id, baseline_snapshot_id, 1 if promoted else 0, reason, decided_at),
            )
            conn.commit()

    def get_active_score_snapshot(
        self, policy_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, Any] | None:
        """Fetch the currently promoted snapshot document for a policy id, scoped to *tenant_id* (E5-S4).

        Joins against ``score_snapshots`` on ``snapshot_id`` since
        ``score_snapshot_promotions`` has no ``tenant_id`` column of its own.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT ssp.snapshot_id FROM score_snapshot_promotions ssp "
                "JOIN score_snapshots ss ON ssp.snapshot_id = ss.snapshot_id "
                "WHERE ssp.policy_id = ? AND ssp.promoted = 1 AND ss.tenant_id = ? "
                "ORDER BY ssp.id DESC LIMIT 1",
                (policy_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        return self.get_score_snapshot(row["snapshot_id"], tenant_id=tenant_id)

    def list_snapshot_promotions(
        self, policy_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict[str, Any]]:
        """List every promotion decision recorded for a policy id, scoped to *tenant_id*, newest first (E5-S4).

        Joins against ``score_snapshots`` on ``snapshot_id`` since
        ``score_snapshot_promotions`` has no ``tenant_id`` column of its own.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT ssp.policy_id, ssp.snapshot_id, ssp.baseline_snapshot_id, ssp.promoted, "
                "ssp.reason, ssp.decided_at "
                "FROM score_snapshot_promotions ssp "
                "JOIN score_snapshots ss ON ssp.snapshot_id = ss.snapshot_id "
                "WHERE ssp.policy_id = ? AND ss.tenant_id = ? ORDER BY ssp.id DESC",
                (policy_id, tenant_id),
            ).fetchall()
        return [
            build_promotion_record(
                policy_id=row["policy_id"],
                snapshot_id=row["snapshot_id"],
                baseline_snapshot_id=row["baseline_snapshot_id"],
                promoted=row["promoted"],
                reason=row["reason"],
                decided_at=row["decided_at"],
            )
            for row in rows
        ]


__all__ = ["_EvalScoringMixin"]
