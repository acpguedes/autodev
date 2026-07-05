"""v2 Evaluation Service API (E5-S3).

API-first (reference doc §2.13): every Evaluation Service capability is
exposed here under ``/v2/evals`` so the Web UI, CLI, and MCP surfaces can all
trigger evals and fetch results through the same contract.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.evals.contract import EvalCase, EvalError, EvalResultConflictError
from backend.evals.service import EvaluationService
from backend.evals.spec import validate_eval_spec
from backend.persistence.database import get_store

SCHEMA_VERSION = "1"

router = APIRouter(prefix="/v2/evals", tags=["evals"])


def get_evaluation_service() -> EvaluationService:
    """Build the Evaluation Service dependency for request handlers.

    Returns:
        A new :class:`EvaluationService` bound to the default durable store.
    """
    return EvaluationService(get_store())


@router.post("/run", status_code=201)
def run_eval(
    body: dict[str, Any],
    service: EvaluationService = Depends(get_evaluation_service),
) -> dict[str, Any]:
    """Validate an ``eval.yaml`` spec and execute (or register) it.

    Offline specs (``mode: offline``) run every declared evaluator over the
    supplied cases and persist a new, versioned result. Online specs
    (``mode: online``) are persisted as a typed-but-minimal registration stub
    — no traffic-splitting/A-B infrastructure exists yet (E5-S4, future story).

    Args:
        body: ``{"spec": {...eval.yaml document...}, "cases": [{"caseId":
            "...", "payload": {...}}, ...], "runId": "..."}``. ``cases`` is
            required for offline mode and ignored for online mode; ``runId``
            is optional (a UUID4 is generated if omitted).
        service: Evaluation Service dependency.

    Returns:
        The persisted result (or online registration) document.

    Raises:
        HTTPException: 422 when the spec is invalid, ``cases`` is missing for
            an offline run, or the run itself fails; 409 when the (optional,
            client-supplied) ``runId`` collides with an already-stored result
            for this eval id+version (results are immutable — ADR-009).
    """
    raw_spec = body.get("spec")
    if not isinstance(raw_spec, dict):
        raise HTTPException(status_code=422, detail="body must carry a 'spec' object")
    validation = validate_eval_spec(raw_spec)
    if not validation.valid or validation.spec is None:
        raise HTTPException(status_code=422, detail={"errors": validation.errors})
    spec = validation.spec
    run_id = body.get("runId")

    if spec.mode == "online":
        try:
            return service.register_online(spec, run_id=run_id)
        except EvalResultConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    raw_cases = body.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise HTTPException(
            status_code=422, detail="body must carry a non-empty 'cases' array for offline mode"
        )
    cases: list[EvalCase] = []
    for index, entry in enumerate(raw_cases):
        if not isinstance(entry, dict):
            raise HTTPException(status_code=422, detail=f"cases[{index}] must be an object")
        payload = entry.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail=f"cases[{index}].payload must be an object")
        cases.append(EvalCase(case_id=str(entry.get("caseId") or index), payload=dict(payload or {})))

    try:
        result = service.run_offline(spec, cases, run_id=run_id)
    except EvalResultConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EvalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.to_document()


@router.get("/results/{namespace}/{name}")
def list_eval_results(
    namespace: str,
    name: str,
    version: str | None = Query(default=None),
    service: EvaluationService = Depends(get_evaluation_service),
) -> dict[str, Any]:
    """List persisted results for an eval id, newest first.

    Args:
        namespace: Eval id namespace segment.
        name: Eval id name segment.
        version: If given, restrict to this eval spec version only.
        service: Evaluation Service dependency.

    Returns:
        The matching results, most recently created first.
    """
    eval_id = f"{namespace}/{name}"
    results = service.list_results(eval_id, version)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "evalId": eval_id,
        "results": [result.to_document() for result in results],
    }


@router.get("/results/{namespace}/{name}/{version}/{run_id}")
def get_eval_result(
    namespace: str,
    name: str,
    version: str,
    run_id: str,
    service: EvaluationService = Depends(get_evaluation_service),
) -> dict[str, Any]:
    """Fetch one persisted eval result.

    Args:
        namespace: Eval id namespace segment.
        name: Eval id name segment.
        version: Eval spec version.
        run_id: Id of the specific run.
        service: Evaluation Service dependency.

    Returns:
        The result document.

    Raises:
        HTTPException: 404 when no such result is stored.
    """
    eval_id = f"{namespace}/{name}"
    result = service.get_result(eval_id, version, run_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"unknown eval result {eval_id!r}@{version!r}#{run_id!r}"
        )
    return result.to_document()


__all__ = ["get_evaluation_service", "router"]
