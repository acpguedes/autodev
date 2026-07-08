"""v2 Control Plane API — run event streaming over SSE (E9-S2-T1/T2/T3).

Exposes ``GET /v2/runs/{run_id}/events/stream``: a Server-Sent Events (SSE)
feed of the catalog events (``backend.events.catalog.EVENT_CATALOG``)
published for one run, backed by the process :class:`~backend.events.bus.EventBus`
(:func:`backend.events.runtime.get_event_bus`) rather than the durable
per-step event log already exposed (non-streaming) by
``GET /v2/flows/runs/{run_id}/events`` in ``backend/api/routers/flows.py``.

Design notes:

* **Resume by cursor (E9-S2-T2).** A client reconnecting sends either the
  standard SSE ``Last-Event-ID`` header or a ``?cursor=`` query parameter
  (the header wins when both are present); the stream then replays only
  events strictly after that cursor via
  :meth:`~backend.events.bus.EventBus.replay_from`, never re-delivering an
  event the client already has.
* **Live tail without polling storms.** The handler subscribes to
  :data:`~backend.events.bus.WILDCARD` purely as a wake-up signal — the
  subscriber callback only flips an :class:`asyncio.Event`, marshaled onto
  the request's event loop with ``call_soon_threadsafe`` since publishers
  may run on a worker thread (FastAPI's threadpool for ``def`` handlers).
  The authoritative ``(cursor, envelope)`` pairs actually sent to the client
  always come from a follow-up :meth:`~backend.events.bus.EventBus.replay_from`
  call, so a missed or coalesced wake-up never drops an event. The
  in-process bus backends have no ``unsubscribe``; a long-lived subscriber
  per connection is an accepted, documented limitation of this iteration.
* **Tenant scoping (E9-S2-T3).** ``PrincipalV2`` has no tenant field yet
  (RBAC is a deferred, no-op seam — see ``backend/api/rbac_v2.py``), so the
  enforced tenant is derived from the run's own record
  (``FlowRunStore.get_run(run_id).tenant_id``), not from the caller. An
  explicit ``?tenantId=`` query parameter is accepted only as a
  double-check: a mismatch reports 404 (not 403), the same as an unknown
  run id, so as to not confirm a run's existence to a caller in the wrong
  tenant.
* **Type filter (E9-S2-T3).** ``?types=`` takes a comma-separated list of
  catalog event type names; any name not in :data:`EVENT_CATALOG` is a 400.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.responses import StreamingResponse

from backend.api.rbac_v2 import require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2, v2_error
from backend.events.bus import EventBus, WILDCARD
from backend.events.catalog import EVENT_CATALOG, EventEnvelope
from backend.events.runtime import get_event_bus
from backend.flows.engine import FlowEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/runs", dependencies=[Depends(require_v2_principal)])

HEARTBEAT_INTERVAL_SEC = 15.0
"""How often an idle live-tail connection sends a ``: ping`` comment frame."""

DISCONNECT_POLL_INTERVAL_SEC = 1.0
"""How often an idle connection re-checks for client disconnect.

Kept well below :data:`HEARTBEAT_INTERVAL_SEC` so a client that closes the
connection is noticed promptly rather than only at the next heartbeat.
"""


def get_flow_engine_v2() -> FlowEngine:
    """Build a fresh :class:`FlowEngine` for run lookups.

    Constructed fresh per request, matching the ``get_flow_engine`` /
    ``get_orchestrator_v2`` convention used by every other ``/v2`` router —
    routers never import app-wide singletons from ``backend.api.main`` (see
    ``backend/api/routers/__init__.py``'s auto-discovery convention).

    Returns:
        A new :class:`FlowEngine`.
    """
    return FlowEngine()


def get_runs_stream_bus() -> EventBus:
    """Zero-argument dependency wrapper over :func:`get_event_bus`.

    FastAPI's ``Depends`` requires a zero-argument callable (or one whose
    parameters are themselves ``Depends``-wrapped); :func:`get_event_bus`
    takes an optional settings override that no request handler supplies.

    Returns:
        The process-wide :class:`~backend.events.bus.EventBus` singleton.
    """
    return get_event_bus()


def _parse_types(types: str | None) -> tuple[str, ...] | None:
    """Parse and validate the ``?types=`` comma-separated filter.

    Args:
        types: Raw query value, or ``None`` when the filter was omitted.

    Returns:
        The validated event type names, or ``None`` when no filter was
        supplied (meaning: every type passes).

    Raises:
        HTTPException: 400 (via :func:`v2_error`) if any listed name is not
            in :data:`EVENT_CATALOG`.
    """
    if not types:
        return None
    requested = tuple(item.strip() for item in types.split(",") if item.strip())
    unknown = [item for item in requested if item not in EVENT_CATALOG]
    if unknown:
        v2_error(400, f"unknown event type(s): {', '.join(unknown)}")
    return requested


def _format_sse_event(cursor: str, envelope: EventEnvelope) -> str:
    """Render one envelope as an ``id``/``event``/``data`` SSE frame.

    Args:
        cursor: Opaque resume cursor identifying this envelope on the bus.
        envelope: The catalog event to render.

    Returns:
        The frame text, including its terminating blank line.
    """
    data = envelope.model_dump(mode="json")
    data["schemaVersion"] = SCHEMA_VERSION_V2
    return f"id: {cursor}\nevent: {envelope.type}\ndata: {json.dumps(data)}\n\n"


async def _stream_events(
    request: Request,
    bus: EventBus,
    run_id: str,
    start_cursor: str | None,
    types: tuple[str, ...] | None,
) -> AsyncIterator[str]:
    """Yield SSE frames: cursor-resumed backlog first, then a live tail.

    Args:
        request: The originating request, polled for client disconnect.
        bus: Event bus to replay from and subscribe to.
        run_id: Run whose partition is streamed.
        start_cursor: Exclusive-start cursor (``None`` streams from the
            beginning of the run's history).
        types: Optional event-type allow-list; ``None`` allows every type.

    Yields:
        SSE frame text, plus periodic ``: ping`` heartbeat comments while
        idle. Disconnect is polled every :data:`DISCONNECT_POLL_INTERVAL_SEC`
        so a closed connection is noticed well before the next heartbeat
        would otherwise be due.
    """
    loop = asyncio.get_running_loop()
    wake = asyncio.Event()

    def _on_event(_envelope: EventEnvelope) -> None:
        loop.call_soon_threadsafe(wake.set)

    bus.subscribe(WILDCARD, _on_event)

    cursor = start_cursor
    idle_elapsed = 0.0
    try:
        while True:
            if await request.is_disconnected():
                return
            for next_cursor, envelope in bus.replay_from(run_id, cursor):
                cursor = next_cursor
                idle_elapsed = 0.0
                if types is None or envelope.type in types:
                    yield _format_sse_event(next_cursor, envelope)
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), timeout=DISCONNECT_POLL_INTERVAL_SEC)
            except asyncio.TimeoutError:
                idle_elapsed += DISCONNECT_POLL_INTERVAL_SEC
                if idle_elapsed >= HEARTBEAT_INTERVAL_SEC:
                    idle_elapsed = 0.0
                    yield ": ping\n\n"
    except asyncio.CancelledError:  # pragma: no cover - depends on server-side disconnect timing
        return


@router.get("/{run_id}/events/stream", tags=["runs"])
async def stream_run_events(
    request: Request,
    run_id: str,
    cursor: str | None = Query(default=None, description="Resume cursor (exclusive-start)."),
    types: str | None = Query(default=None, description="Comma-separated event type allow-list."),
    tenant_id: str | None = Query(default=None, alias="tenantId", description="Expected tenant; must match the run's own tenant."),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    engine: FlowEngine = Depends(get_flow_engine_v2),
    bus: EventBus = Depends(get_runs_stream_bus),
) -> StreamingResponse:
    """Stream a run's catalog events as Server-Sent Events.

    Resumes past a ``Last-Event-ID`` header (preferred) or ``?cursor=``
    query parameter, optionally filtered by ``?types=``, scoped to the
    run's own tenant.

    Args:
        request: The incoming request (used for disconnect detection).
        run_id: Run whose events are streamed.
        cursor: Fallback resume cursor when no ``Last-Event-ID`` header is
            sent.
        types: Optional comma-separated event-type filter.
        tenant_id: Optional explicit tenant check; must match the run's
            owning tenant when supplied.
        last_event_id: Standard SSE resume header; wins over ``?cursor=``.
        engine: Flow engine dependency, used only for its run store.
        bus: Event bus dependency to replay from and subscribe to.

    Returns:
        A ``text/event-stream`` response.

    Raises:
        HTTPException: 404 (via :func:`v2_error`) if ``run_id`` is unknown
            or ``tenantId`` does not match the run's tenant; 400 if
            ``types`` contains an uncataloged event type.
    """
    run = engine.runs.get_run(run_id)
    if run is None or (tenant_id is not None and tenant_id != run.tenant_id):
        v2_error(404, f"unknown run {run_id!r}")

    parsed_types = _parse_types(types)
    start_cursor = last_event_id if last_event_id is not None else cursor

    return StreamingResponse(
        _stream_events(request, bus, run_id, start_cursor, parsed_types),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
