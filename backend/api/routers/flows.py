"""v2 Flow API: registration, validation, runs, triggers, and event store.

API-first (reference doc §2.13): every Orchestration Engine capability is
exposed here under ``/v2/flows`` so the Web UI, CLI, and MCP surfaces can all
drive flows through the same contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.flows.engine import FlowEngine, FlowRunError
from backend.flows.human import (
    FlowHumanDecisionError,
    FlowHumanError,
    FlowHumanService,
    FlowHumanStateError,
)
from backend.flows.manifest import validate_flow_manifest
from backend.flows.triggers import TriggerError, due_cron_triggers, normalize_trigger

router = APIRouter(prefix="/v2/flows", tags=["flows"])


def get_flow_engine() -> FlowEngine:
    """Build the flow engine dependency for request handlers.

    Returns:
        A new :class:`FlowEngine` bound to the default durable store.
    """
    return FlowEngine()


def get_human_service(
    engine: FlowEngine = Depends(get_flow_engine),
) -> FlowHumanService:
    """Build the human-in-the-loop service dependency for request handlers.

    Args:
        engine: Flow engine dependency (shared so test overrides propagate).

    Returns:
        A :class:`FlowHumanService` bound to the request's engine.
    """
    return FlowHumanService(engine=engine)


@router.post("", status_code=201)
def register_flow(
    manifest: dict[str, Any],
    engine: FlowEngine = Depends(get_flow_engine),
) -> dict[str, Any]:
    """Validate and register a flow definition.

    Args:
        manifest: Raw ``flow.yaml`` document as JSON.
        engine: Flow engine dependency.

    Returns:
        A registration document for the stored flow version.

    Raises:
        HTTPException: 422 when the manifest is invalid.
    """
    result = validate_flow_manifest(manifest)
    if not result.valid or result.manifest is None:
        raise HTTPException(status_code=422, detail={"errors": result.errors})
    registered = engine.registry.register(result.manifest)
    return {
        "schemaVersion": "1",
        "registered": {"id": registered.id, "version": registered.version},
    }


@router.post("/validate")
def validate_flow(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate a flow definition without registering it.

    Args:
        manifest: Raw ``flow.yaml`` document as JSON.

    Returns:
        The validation outcome with every error found.
    """
    result = validate_flow_manifest(manifest)
    return {"schemaVersion": "1", "valid": result.valid, "errors": result.errors}


@router.get("")
def list_flows(engine: FlowEngine = Depends(get_flow_engine)) -> dict[str, Any]:
    """List the registered flow catalog.

    Args:
        engine: Flow engine dependency.

    Returns:
        The catalog document.
    """
    return engine.registry.catalog()


@router.post("/cron/tick")
def cron_tick(
    body: dict[str, Any] | None = None,
    engine: FlowEngine = Depends(get_flow_engine),
) -> dict[str, Any]:
    """Start a run for every flow whose cron trigger is due now.

    Args:
        body: Optional ``{"at": "<ISO-8601>"}`` override of the tick time
            (used by tests and backfills).
        engine: Flow engine dependency.

    Returns:
        The runs started by this tick.

    Raises:
        HTTPException: 422 when the ``at`` override is not a valid timestamp.
    """
    at_text = (body or {}).get("at")
    if at_text is not None:
        try:
            at = datetime.fromisoformat(str(at_text))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        at = datetime.now(timezone.utc)
    started: list[dict[str, Any]] = []
    for manifest, schedule in due_cron_triggers(engine.registry.list_flows(), at):
        trigger = normalize_trigger(manifest, "cron")
        run = engine.start_run(
            manifest.id,
            version_range=manifest.version,
            input={},
            trigger=trigger.to_document(),
        )
        started.append({"runId": run.run_id, "flowId": manifest.id, "schedule": schedule})
    return {"schemaVersion": "1", "started": started}


@router.get("/runs/{run_id}")
def get_run(
    run_id: str, engine: FlowEngine = Depends(get_flow_engine)
) -> dict[str, Any]:
    """Fetch a run with its steps.

    Args:
        run_id: Id of the run.
        engine: Flow engine dependency.

    Returns:
        The run document including its ordered steps.

    Raises:
        HTTPException: 404 when the run is unknown.
    """
    run = engine.runs.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    document = run.to_document()
    document["steps"] = [step.to_document() for step in engine.runs.list_steps(run_id)]
    return document


@router.get("/runs/{run_id}/events")
def get_run_events(
    run_id: str, engine: FlowEngine = Depends(get_flow_engine)
) -> dict[str, Any]:
    """Fetch a run's ordered event store.

    Args:
        run_id: Id of the run.
        engine: Flow engine dependency.

    Returns:
        The run's events in emission order.

    Raises:
        HTTPException: 404 when the run is unknown.
    """
    if engine.runs.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    return {
        "schemaVersion": "1",
        "events": [event.to_document() for event in engine.runs.list_events(run_id)],
    }


@router.get("/runs/{run_id}/pending-human")
def get_pending_human(
    run_id: str, service: FlowHumanService = Depends(get_human_service)
) -> dict[str, Any]:
    """Fetch the pending human request of a paused run (E3-S4).

    Args:
        run_id: Id of the run.
        service: Human-in-the-loop service dependency.

    Returns:
        The pending request document (node id, prompt, form, expiry).

    Raises:
        HTTPException: 404 when the run is unknown; 409 when the run is not
            waiting for a human decision.
    """
    try:
        pending = service.pending(run_id)
    except FlowHumanError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if pending is None:
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id!r} is not waiting for a human decision",
        )
    return pending.to_document()


@router.post("/runs/{run_id}/human-decision")
def post_human_decision(
    run_id: str,
    body: dict[str, Any],
    engine: FlowEngine = Depends(get_flow_engine),
    service: FlowHumanService = Depends(get_human_service),
) -> dict[str, Any]:
    """Record a human decision and resume the paused run (E3-S4).

    Args:
        run_id: Id of the paused run.
        body: ``{"decision": {...}, "actor": "..."}``; ``actor`` defaults to
            ``"anonymous"`` and is recorded on the decision event.
        engine: Flow engine dependency (used to render the run's steps).
        service: Human-in-the-loop service dependency.

    Returns:
        The resulting run document including its ordered steps.

    Raises:
        HTTPException: 404 for unknown runs, 409 when the run is not waiting,
            422 for invalid decisions or expired waits (the timeout route is
            taken before the 422 is returned — fail closed on the SLA).
    """
    decision = body.get("decision")
    if not isinstance(decision, dict):
        raise HTTPException(
            status_code=422, detail="body must carry a 'decision' object"
        )
    actor = str(body.get("actor") or "anonymous")
    try:
        run = service.decide(run_id, decision, actor=actor)
    except FlowHumanStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FlowHumanDecisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FlowHumanError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    document = run.to_document()
    document["steps"] = [
        step.to_document() for step in engine.runs.list_steps(run.run_id)
    ]
    return document


@router.post("/human/expire")
def expire_human_waits(
    body: dict[str, Any] | None = None,
    service: FlowHumanService = Depends(get_human_service),
) -> dict[str, Any]:
    """Expire every due human wait (operator/cron surface, E3-S4).

    Args:
        body: Optional ``{"at": "<ISO-8601>"}`` override of the expiry moment
            (used by tests and backfills).
        service: Human-in-the-loop service dependency.

    Returns:
        The ids of the runs routed through their timeout edges.

    Raises:
        HTTPException: 422 when the ``at`` override is not a valid timestamp.
    """
    at_text = (body or {}).get("at")
    at: datetime | None = None
    if at_text is not None:
        try:
            at = datetime.fromisoformat(str(at_text))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"schemaVersion": "1", "expired": service.expire_due(at)}


@router.get("/{namespace}/{name}")
def get_flow_versions(
    namespace: str,
    name: str,
    engine: FlowEngine = Depends(get_flow_engine),
) -> dict[str, Any]:
    """List the registered versions of one flow.

    Args:
        namespace: Flow id namespace segment.
        name: Flow id name segment.
        engine: Flow engine dependency.

    Returns:
        The flow's registered versions, oldest first.

    Raises:
        HTTPException: 404 when the flow has no registered versions.
    """
    flow_id = f"{namespace}/{name}"
    manifests = engine.registry.list_flows(flow_id=flow_id)
    if not manifests:
        raise HTTPException(status_code=404, detail=f"unknown flow {flow_id!r}")
    return {
        "schemaVersion": "1",
        "id": flow_id,
        "versions": [
            {"version": manifest.version, "name": manifest.name}
            for manifest in manifests
        ],
    }


@router.post("/{namespace}/{name}/runs", status_code=201)
def start_run(
    namespace: str,
    name: str,
    body: dict[str, Any] | None = None,
    engine: FlowEngine = Depends(get_flow_engine),
) -> dict[str, Any]:
    """Start (and synchronously execute) a run of a registered flow.

    Args:
        namespace: Flow id namespace segment.
        name: Flow id name segment.
        body: ``{"input": {...}, "versionRange": "...", "tenantId": "..."}``.
        engine: Flow engine dependency.

    Returns:
        The terminal run document including steps.

    Raises:
        HTTPException: 404 for unknown flows, 422 for invalid input.
    """
    payload = body or {}
    flow_id = f"{namespace}/{name}"
    try:
        run = engine.start_run(
            flow_id,
            version_range=str(payload.get("versionRange", "*")),
            input=payload.get("input") or {},
            trigger={"type": "api"},
            tenant_id=str(payload.get("tenantId", "default")),
        )
    except FlowRunError as exc:
        status = 404 if "No flow" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    document = run.to_document()
    document["steps"] = [
        step.to_document() for step in engine.runs.list_steps(run.run_id)
    ]
    return document


@router.post("/{namespace}/{name}/trigger", status_code=201)
def trigger_run(
    namespace: str,
    name: str,
    body: dict[str, Any] | None = None,
    engine: FlowEngine = Depends(get_flow_engine),
) -> dict[str, Any]:
    """Start a run through a declared trigger (message/webhook/event).

    The trigger type must be declared by the flow's manifest (fail closed);
    ``event`` triggers must also match a subscribed event name.

    Args:
        namespace: Flow id namespace segment.
        name: Flow id name segment.
        body: ``{"type": "message|webhook|event", "event": "...",
            "input": {...}, "payload": {...}}``.
        engine: Flow engine dependency.

    Returns:
        The terminal run document.

    Raises:
        HTTPException: 404 for unknown flows, 422 for undeclared triggers or
            invalid input.
    """
    payload = body or {}
    flow_id = f"{namespace}/{name}"
    trigger_type = str(payload.get("type", "message"))
    try:
        manifest = engine.registry.resolve(flow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        trigger = normalize_trigger(
            manifest,
            trigger_type,
            event=payload.get("event"),
            payload=payload.get("payload") or {},
        )
        run = engine.start_run(
            flow_id,
            version_range=manifest.version,
            input=payload.get("input") or {},
            trigger=trigger.to_document(),
        )
    except (TriggerError, FlowRunError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return run.to_document()


__all__ = ["get_flow_engine", "get_human_service", "router"]
