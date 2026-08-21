"""Read-only session/run listing endpoints backing the ``/v2`` API (E47-S5)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from backend.agents import AGENT_METADATA_MODELS
from backend.orchestrator.service._shared import OrchestratorState
from backend.orchestrator.service.models import RunStatus, RunSummary, SessionSummary
from backend.orchestrator.service.summaries import build_run_summary, build_session_summary
from backend.persistence.tenancy import DEFAULT_TENANT_ID


class QueryMixin(OrchestratorState):
    """Session and run listings, and the agent-contract catalog."""

    def describe_agent_contracts(self) -> Dict[str, Dict[str, Any]]:
        """Return JSON-schema contracts for machine-readable agent metadata."""

        return {
            agent_name: model.model_json_schema()  # type: ignore[attr-defined]
            for agent_name, model in AGENT_METADATA_MODELS.items()
        }

    def list_sessions(self, *, tenant_id: str = DEFAULT_TENANT_ID) -> List[SessionSummary]:
        """List all known sessions for ``tenant_id``, each with its full history.

        Costs one message query per session; prefer
        :meth:`list_sessions_page` for anything that only needs a page.
        """
        return [
            build_session_summary(self._store, record, tenant_id=tenant_id)
            for record in self._store.list_sessions(tenant_id=tenant_id)
        ]

    def list_sessions_page(
        self, *, limit: int, offset: int, tenant_id: str = DEFAULT_TENANT_ID
    ) -> Tuple[List[SessionSummary], int]:
        """Return one page of sessions plus the tenant's total session count (E44-S3).

        Paginates in the store rather than loading every session and slicing,
        and leaves each summary's ``history`` empty — listings surface
        ``message_count``/``last_activity`` instead, so a page costs a fixed
        number of queries regardless of how many sessions or messages the
        tenant has. Fetch a single session (:meth:`get_session`) to read its
        conversation.

        Args:
            limit: Maximum number of sessions to return.
            offset: Number of sessions to skip, in listing order.
            tenant_id: Tenant to scope the listing to.

        Returns:
            A ``(page, total)`` pair.
        """
        records, total = self._store.list_sessions_page(
            limit=limit, offset=offset, tenant_id=tenant_id
        )
        page = [
            SessionSummary(
                session_id=record["id"],
                goal=record["goal"],
                plan=list(record["plan"] or []),
                status=RunStatus.AWAITING_INPUT,
                history=[],
                message_count=int(record.get("message_count", 0)),
                last_activity=record.get("last_activity"),
            )
            for record in records
        ]
        return page, total

    def get_session(
        self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> SessionSummary:
        """Fetch a single session by id, scoped to ``tenant_id``.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        record = self._store.get_session(session_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return build_session_summary(self._store, record, tenant_id=tenant_id)

    def list_runs(
        self, session_id: str, *, tenant_id: str = DEFAULT_TENANT_ID
    ) -> List[RunSummary]:
        """List all historical runs for a session, scoped to ``tenant_id``.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return [
            build_run_summary(record)
            for record in self._store.list_runs(session_id, tenant_id=tenant_id)
        ]

    def list_runs_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> Tuple[List[RunSummary], int]:
        """Return one page of a session's runs plus its total run count (E44-S3).

        Same ordering and per-run shape as :meth:`list_runs`; the window is
        applied in SQL instead of in the API layer.

        Args:
            session_id: Identifier of the session.
            limit: Maximum number of runs to return.
            offset: Number of runs to skip, in listing order.
            tenant_id: Tenant the session must belong to.

        Returns:
            A ``(page, total)`` pair.

        Raises:
            KeyError: If ``session_id`` does not exist for ``tenant_id``.
        """
        session_record = self._store.get_session(session_id, tenant_id=tenant_id)
        if session_record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        records, total = self._store.list_runs_page(
            session_id, limit=limit, offset=offset, tenant_id=tenant_id
        )
        return [build_run_summary(record) for record in records], total

    def get_run(self, run_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> RunSummary:
        """Fetch a single run by id without knowing its session (E44-S1).

        Args:
            run_id: Identifier of the run.
            tenant_id: Tenant the run must belong to; a run owned by another
                tenant is treated exactly like a nonexistent one.

        Returns:
            The run's :class:`~backend.orchestrator.service.models.RunSummary`,
            identical in shape to the entries :meth:`list_runs` returns.

        Raises:
            KeyError: If ``run_id`` does not exist for ``tenant_id``.
        """
        record = self._store.get_run(run_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return build_run_summary(record)


__all__ = ["QueryMixin"]
