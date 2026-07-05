"""Evaluation Service: run offline evals, register online stubs, persist results (E5-S3).

Ties the :class:`~backend.evals.runner.EvalRunner` to durable storage: it runs
(or, for ``mode: online``, registers) an :class:`~backend.evals.contract.EvalSpec`,
persists the immutable, versioned result, applies the spec's quality gate, and
emits ``on_event`` trace events — mirroring the
:class:`backend.reasoning.service.ReasoningService` shape.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, Sequence

from backend.evals.contract import EvalCase, EvalError, EvalResultConflictError, EvalSpec, TraceEvent
from backend.evals.results import EVAL_RESULT_SCHEMA_VERSION, EvalResult, RunMetrics
from backend.evals.runner import EvalRunner

try:  # pragma: no cover - psycopg is a hard dependency per backend/requirements.txt
    import psycopg

    _STORE_INTEGRITY_ERRORS: tuple[type[Exception], ...] = (sqlite3.IntegrityError, psycopg.IntegrityError)
except ImportError:  # pragma: no cover - defensive: psycopg missing in a SQLite-only environment
    _STORE_INTEGRITY_ERRORS = (sqlite3.IntegrityError,)


class EvalResultStore(Protocol):
    """Structural interface for the durable eval-result store.

    Concrete implementations live on :class:`~backend.persistence.sqlite_adapter.SQLiteStore`
    and ``PostgresStore``, selected via :func:`backend.persistence.database.get_store`.
    """

    def create_eval_result(
        self, *, eval_id: str, eval_version: str, run_id: str, document: dict[str, Any]
    ) -> None:
        """Persist one eval result document. Never overwrites an existing run."""
        ...

    def get_eval_result(self, eval_id: str, eval_version: str, run_id: str) -> dict[str, Any] | None:
        """Fetch one eval result document, or ``None`` if it does not exist."""
        ...

    def list_eval_results(self, eval_id: str, eval_version: str | None = None) -> list[dict[str, Any]]:
        """List eval result documents for an id, newest first, optionally filtered by version."""
        ...


class EvaluationService:
    """Runs offline evals (and registers online stubs), persisting every result."""

    def __init__(
        self,
        store: EvalResultStore,
        *,
        runner: EvalRunner | None = None,
        on_event: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        """Initialize the service with a durable store and an eval runner.

        Args:
            store: Durable store the service persists results to.
            runner: Eval runner used for offline execution; a default
                (offline-stub-backed) :class:`EvalRunner` is created if omitted.
            on_event: Trace sink; receives ``eval.run.*`` lifecycle events.
        """
        self._store = store
        self._runner = runner or EvalRunner()
        self._on_event = on_event

    def run_offline(
        self, spec: EvalSpec, cases: Sequence[EvalCase], *, run_id: str | None = None
    ) -> EvalResult:
        """Run every evaluator in ``spec`` over ``cases`` and persist the result.

        Args:
            spec: The eval spec to run; must declare ``mode: offline``.
            cases: Dataset cases to score.
            run_id: Explicit run id; a fresh UUID4 is generated if omitted.
                Re-running the same spec always produces a new, distinct
                result — results are immutable and versioned (never
                overwritten) by ``(eval_id, eval_version, run_id)``.

        Returns:
            The persisted, immutable :class:`~backend.evals.results.EvalResult`.

        Raises:
            EvalError: If ``spec.mode`` is not ``"offline"``, or if the run
                fails (e.g. an unregistered evaluator kind or invalid gate
                expression).
            EvalResultConflictError: If ``run_id`` was explicitly given and a
                result for ``(spec.id, spec.version, run_id)`` already exists.
        """
        if spec.mode != "offline":
            raise EvalError(f"run_offline requires mode='offline', got {spec.mode!r}")
        run_id = run_id or str(uuid.uuid4())
        self._emit("eval.run.started", {"evalId": spec.id, "evalVersion": spec.version, "runId": run_id})
        try:
            evaluator_results, metrics = self._runner.run(spec, cases)
            gate_passed, gate_reason = self._runner.evaluate_gate(spec.gate, metrics)
            result = EvalResult(
                eval_id=spec.id,
                eval_version=spec.version,
                run_id=run_id,
                mode=spec.mode,
                dataset_ref=spec.dataset.ref,
                dataset_split=spec.dataset.split,
                dataset_size=len(cases),
                evaluator_results=evaluator_results,
                metrics=metrics,
                gate_passed=gate_passed,
                gate_reason=gate_reason,
                created_at=_utcnow(),
            )
            self._store_result(
                eval_id=spec.id, eval_version=spec.version, run_id=run_id, document=result.to_document()
            )
        except EvalError as exc:
            self._emit(
                "eval.run.failed",
                {"evalId": spec.id, "evalVersion": spec.version, "runId": run_id, "error": str(exc)},
            )
            raise
        self._emit(
            "eval.run.completed",
            {
                "evalId": spec.id,
                "evalVersion": spec.version,
                "runId": run_id,
                "gatePassed": gate_passed,
            },
        )
        return result

    def register_online(self, spec: EvalSpec, *, run_id: str | None = None) -> dict[str, Any]:
        """Persist a typed-but-minimal record of an ``online`` eval spec.

        No traffic-splitting/A-B infrastructure exists yet (E5-S4, future
        story, see ADR-009): this accepts and durably stores the declared
        ``online.publish_scores``/``online.ab_test`` shape without running
        anything against live traffic.

        Args:
            spec: The eval spec to register; must declare ``mode: online``.
            run_id: Explicit registration id; a fresh UUID4 is generated if omitted.

        Returns:
            The persisted registration document.

        Raises:
            EvalError: If ``spec.mode`` is not ``"online"``.
            EvalResultConflictError: If ``run_id`` was explicitly given and a
                result for ``(spec.id, spec.version, run_id)`` already exists.
        """
        if spec.mode != "online":
            raise EvalError(f"register_online requires mode='online', got {spec.mode!r}")
        run_id = run_id or str(uuid.uuid4())
        online = spec.online
        ab_test = None
        if online is not None and online.ab_test is not None:
            ab_test = {
                "control": online.ab_test.control,
                "variant": online.ab_test.variant,
                "traffic": online.ab_test.traffic,
                "promoteIf": online.ab_test.promote_if,
                "minSamples": online.ab_test.min_samples,
            }
        document = {
            "schemaVersion": EVAL_RESULT_SCHEMA_VERSION,
            "evalId": spec.id,
            "evalVersion": spec.version,
            "runId": run_id,
            "mode": "online",
            "dataset": {"ref": spec.dataset.ref, "split": spec.dataset.split, "size": spec.dataset.size},
            "evaluators": [],
            "metrics": RunMetrics().to_document(),
            "gate": {"passed": True, "reason": "online mode: no offline gate evaluated"},
            "online": {
                "publishScores": online.publish_scores if online is not None else False,
                "abTest": ab_test,
            },
            "createdAt": _utcnow(),
        }
        self._store_result(eval_id=spec.id, eval_version=spec.version, run_id=run_id, document=document)
        self._emit(
            "eval.run.registered_online",
            {"evalId": spec.id, "evalVersion": spec.version, "runId": run_id},
        )
        return document

    def get_result(self, eval_id: str, eval_version: str, run_id: str) -> EvalResult | None:
        """Fetch one persisted result.

        Args:
            eval_id: Id of the eval spec.
            eval_version: Version of the eval spec.
            run_id: Id of the specific run.

        Returns:
            The result, or ``None`` if no such run is stored.
        """
        document = self._store.get_eval_result(eval_id, eval_version, run_id)
        return EvalResult.from_document(document) if document is not None else None

    def list_results(self, eval_id: str, eval_version: str | None = None) -> list[EvalResult]:
        """List persisted results for an eval id, newest first.

        Args:
            eval_id: Id of the eval spec.
            eval_version: If given, restrict to this version only.

        Returns:
            The matching results.
        """
        return [
            EvalResult.from_document(document)
            for document in self._store.list_eval_results(eval_id, eval_version)
        ]

    def _store_result(self, *, eval_id: str, eval_version: str, run_id: str, document: dict[str, Any]) -> None:
        """Persist a result document, translating a store-level uniqueness
        violation into a typed :class:`~backend.evals.contract.EvalResultConflictError`.

        The ``eval_results`` table enforces ``UNIQUE(eval_id, eval_version,
        run_id)`` (results are immutable — ADR-009), so reusing a ``run_id``
        raises a backend-specific integrity error (``sqlite3.IntegrityError``
        or ``psycopg.IntegrityError``); this normalizes both into one
        service-level error the API layer can map to a client (4xx) response
        instead of letting a raw database exception escape as a 500.

        Args:
            eval_id: Id of the eval spec.
            eval_version: Version of the eval spec.
            run_id: Id of this run.
            document: The result document to persist.

        Raises:
            EvalResultConflictError: If ``(eval_id, eval_version, run_id)`` is
                already stored.
        """
        try:
            self._store.create_eval_result(
                eval_id=eval_id, eval_version=eval_version, run_id=run_id, document=document
            )
        except _STORE_INTEGRITY_ERRORS as exc:
            raise EvalResultConflictError(
                f"a result for {eval_id}@{eval_version}#{run_id} already exists"
            ) from exc

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        """Emit a service-level lifecycle event to the trace sink, if configured.

        Args:
            name: Dotted event name.
            payload: Structured payload for the event.
        """
        if self._on_event is not None:
            self._on_event(TraceEvent(sequence=-1, name=name, payload=payload, timestamp=time.time()))


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


__all__ = ["EvalResultStore", "EvaluationService"]
