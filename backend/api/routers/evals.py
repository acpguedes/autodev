"""v2 Evaluation Service API (E5-S3, E5-S4).

API-first (reference doc §2.13): every Evaluation Service capability is
exposed here under ``/v2/evals`` so the Web UI, CLI, and MCP surfaces can all
trigger evals and fetch results through the same contract. E5-S4 adds the
``publish`` endpoint: aggregate persisted results into a versioned score
snapshot and decide whether to promote it for a routing policy, closing the
feedback loop (reference §9.5).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.evals.contract import ABTestSpec, EvalCase, EvalError, EvalResultConflictError
from backend.evals.service import EvaluationService
from backend.evals.spec import validate_eval_spec
from backend.persistence.database import get_store
from backend.routing.feedback import RoutingFeedbackService

SCHEMA_VERSION = "1"

router = APIRouter(prefix="/v2/evals", tags=["evals"])


def get_evaluation_service() -> EvaluationService:
    """Build the Evaluation Service dependency for request handlers.

    Returns:
        A new :class:`EvaluationService` bound to the default durable store.
    """
    return EvaluationService(get_store())


def get_routing_feedback_service() -> RoutingFeedbackService:
    """Build the Routing Feedback Service dependency for request handlers.

    Returns:
        A new :class:`RoutingFeedbackService` bound to the default durable
        store — the same store :func:`get_evaluation_service` publishes
        snapshots to, so a promotion decided here is immediately visible to
        ``/v2/select`` (both share the process-wide cached store).
    """
    return RoutingFeedbackService(get_store())


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


@router.post("/{namespace}/{name}/publish", status_code=201)
def publish_snapshot(
    namespace: str,
    name: str,
    body: dict[str, Any],
    service: EvaluationService = Depends(get_evaluation_service),
    feedback: RoutingFeedbackService = Depends(get_routing_feedback_service),
) -> dict[str, Any]:
    """Publish a score snapshot from persisted results and decide its promotion (E5-S4).

    Aggregates every persisted :class:`~backend.evals.results.EvalResult` for
    this eval id (optionally restricted to ``evalVersion``) into a new,
    versioned :class:`~backend.routing.contract.ScoreSnapshot`, then decides
    whether to promote it as ``policyId``'s active snapshot — guarded by
    ``minSamples`` (hysteresis) and ``promoteIf`` (regression criterion,
    reference §9.4/§9.5). The decision is always persisted and traced, whether
    or not the snapshot is promoted (reference §9.6 fail-closed default).

    Args:
        namespace: Eval id namespace segment.
        name: Eval id name segment.
        body: ``{"policyId": "...", "evalVersion": "..." (optional),
            "promoteIf": "variant.quality >= control.quality and ..." (optional,
            default: always promote once the sample guard passes),
            "minSamples": 0 (optional, default 0 = no minimum)}``.
        service: Evaluation Service dependency.
        feedback: Routing Feedback Service dependency.

    Returns:
        ``{"schemaVersion", "snapshot": <ScoreSnapshot document>, "promotion":
        <PromotionDecision document>}``.

    Raises:
        HTTPException: 422 when ``policyId`` is missing or no results are
            persisted for this eval id to aggregate.
    """
    eval_id = f"{namespace}/{name}"
    policy_id = body.get("policyId")
    if not isinstance(policy_id, str) or not policy_id:
        raise HTTPException(status_code=422, detail="body must carry a non-empty 'policyId'")
    eval_version = body.get("evalVersion")
    if eval_version is not None and not isinstance(eval_version, str):
        raise HTTPException(status_code=422, detail="'evalVersion' must be a string when given")
    raw_min_samples = body.get("minSamples", 0)
    if not isinstance(raw_min_samples, int) or isinstance(raw_min_samples, bool) or raw_min_samples < 0:
        raise HTTPException(status_code=422, detail="'minSamples' must be a non-negative integer")

    try:
        snapshot = service.publish_snapshot(eval_id, eval_version=eval_version)
    except EvalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ab_test = ABTestSpec(promote_if=str(body.get("promoteIf", "")), min_samples=raw_min_samples)
    decision = feedback.decide_promotion(snapshot, policy_id=policy_id, ab_test=ab_test)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "snapshot": snapshot.to_document(),
        "promotion": decision.to_document(),
    }


@router.get("/{namespace}/{name}/snapshots")
def list_snapshots(
    namespace: str,
    name: str,
    policy_id: str | None = Query(default=None, alias="policyId"),
    feedback: RoutingFeedbackService = Depends(get_routing_feedback_service),
) -> dict[str, Any]:
    """Inspect the promotion history for a policy id (E5-S4).

    Args:
        namespace: Eval id namespace segment (kept for URL symmetry with the
            other ``/v2/evals/{namespace}/{name}/...`` routes; snapshots
            themselves are not scoped by eval id, only promotions are).
        name: Eval id name segment.
        policy_id: Routing policy id whose promotion history to list.
        feedback: Routing Feedback Service dependency.

    Returns:
        ``{"schemaVersion", "promotions": [<PromotionDecision document>, ...]}``.

    Raises:
        HTTPException: 422 when ``policyId`` is missing.
    """
    del namespace, name  # URL symmetry only — promotions are keyed by policy_id, not eval id
    if not policy_id:
        raise HTTPException(status_code=422, detail="query must carry a non-empty 'policyId'")
    promotions = feedback.list_promotions(policy_id)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "promotions": [decision.to_document() for decision in promotions],
    }


__all__ = ["get_evaluation_service", "get_routing_feedback_service", "router"]
