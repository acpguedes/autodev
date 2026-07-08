"""Tests for the run event streaming SSE endpoint (E9-S2-T1/T2/T3).

``TestClient`` cannot exercise ``_stream_events``'s live-tail generator: the
installed ``httpx.ASGITransport`` fully drains the ASGI app coroutine before
constructing any response, so an infinite generator hangs the test. The SSE
framing/resume/filter/heartbeat/disconnect behavior is therefore tested by
calling ``_stream_events``/``stream_run_events`` directly as plain async
functions (bypassing HTTP/ASGI entirely) and driving the resulting async
generator with bounded ``__anext__()`` calls inside ``asyncio.run(...)``.
Only the fast-fail 404/400 paths of ``stream_run_events`` (which raise before
any generator is ever constructed) are safe to drive this way too — and are,
for consistency with the rest of this module.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from fastapi import HTTPException

import backend.api.routers.runs_stream_v2 as runs_stream_v2
from backend.api.routers.runs_stream_v2 import (
    _format_sse_event,
    _parse_types,
    _stream_events,
    stream_run_events,
)
from backend.api.v2_common import SCHEMA_VERSION_V2
from backend.events.bus import EventBus, InMemoryEventBus
from backend.events.catalog import make_envelope
from backend.events.runtime import get_event_bus, reset_event_bus_for_tests
from backend.flows.engine import FlowEngine
from backend.flows.handlers import CallableRegistry, build_default_handlers
from backend.persistence.sqlite_adapter import SQLiteStore


_SAMPLE_DATA: dict[str, dict[str, Any]] = {
    "flow.run.started": {"flowId": "autodev/flow-stream", "flowVersion": "1.0.0"},
    "run.step.started": {"stepKey": "only", "agent": "autodev/skill-echo"},
    "run.step.completed": {"stepKey": "only", "status": "completed", "attempt": 1},
    "flow.run.completed": {"status": "completed", "costUsd": 0.0, "tokens": 0},
}
"""Minimal schema-valid ``data`` payloads for the catalog types used below."""


def _publish(bus: EventBus, run_id: str, type_: str, tenant_id: str = "default") -> str:
    """Publish a minimal, schema-valid catalog event onto a run's partition.

    Args:
        bus: Bus to publish on.
        run_id: Partition key (the run id).
        type_: Catalog event type name (must be a key of ``_SAMPLE_DATA``).
        tenant_id: Tenant for the envelope.

    Returns:
        The published envelope's event id.
    """
    return bus.publish(
        make_envelope(
            type_,
            tenant_id=tenant_id,
            partition_key=run_id,
            data=_SAMPLE_DATA[type_],
        )
    )


class _FakeRequest:
    """Stand-in for :class:`starlette.requests.Request` that never disconnects."""

    def __init__(self) -> None:
        """Initialize the disconnect-call counter."""
        self.calls = 0

    async def is_disconnected(self) -> bool:
        """Report the client as always connected."""
        self.calls += 1
        return False


class _DisconnectingRequest:
    """Stand-in that reports disconnected starting from its second poll."""

    def __init__(self, connected_polls: int = 1) -> None:
        """Initialize with the number of polls that report "connected".

        Args:
            connected_polls: How many leading ``is_disconnected()`` calls
                return ``False`` before switching to ``True``.
        """
        self.calls = 0
        self._connected_polls = connected_polls

    async def is_disconnected(self) -> bool:
        """Report disconnected once the connected-poll budget is exhausted."""
        self.calls += 1
        return self.calls > self._connected_polls


@dataclass
class _FakeRun:
    """Minimal stand-in for :class:`~backend.flows.state.FlowRunRecord`."""

    tenant_id: str


class _FakeRunStore:
    """Minimal stand-in for :class:`~backend.flows.state.FlowRunStore`."""

    def __init__(self, runs: dict[str, _FakeRun]) -> None:
        """Store the fixed run-id to run mapping."""
        self._runs = runs

    def get_run(self, run_id: str) -> _FakeRun | None:
        """Look up a run by id, or ``None`` if unknown."""
        return self._runs.get(run_id)


class _FakeEngine:
    """Minimal stand-in for :class:`~backend.flows.engine.FlowEngine`.

    ``stream_run_events`` only ever touches ``engine.runs.get_run(run_id)``,
    so a real engine (and its database) is unnecessary for handler-level
    tests.
    """

    def __init__(self, runs: dict[str, _FakeRun]) -> None:
        """Wrap the fixed run-id to run mapping in a fake run store."""
        self.runs = _FakeRunStore(runs)


async def _collect(agen: AsyncIterator[str], count: int) -> list[str]:
    """Drive an async generator for exactly ``count`` items, then close it.

    Args:
        agen: The async generator (or any async iterator) under test.
        count: Number of items to pull via ``__anext__()``.

    Returns:
        The collected items, in order.
    """
    frames = [await agen.__anext__() for _ in range(count)]
    aclose = getattr(agen, "aclose", None)
    if aclose is not None:
        await aclose()
    return frames


class TestParseTypes:
    """Unit tests for the ``?types=`` query parser/validator."""

    def test_none_and_blank_pass_everything(self) -> None:
        """No filter and an empty string both mean "allow every type"."""
        assert _parse_types(None) is None
        assert _parse_types("") is None

    def test_valid_types_are_parsed_and_trimmed(self) -> None:
        """Comma-separated, whitespace-padded type names are parsed cleanly."""
        assert _parse_types("flow.run.started, flow.run.completed") == (
            "flow.run.started",
            "flow.run.completed",
        )

    def test_unknown_type_raises_400(self) -> None:
        """An uncataloged event type name is rejected with a 400."""
        with pytest.raises(HTTPException) as excinfo:
            _parse_types("not.a.real.event")
        assert excinfo.value.status_code == 400


class TestFormatSseEvent:
    """Unit tests for the ``id``/``event``/``data`` SSE frame renderer."""

    def test_frame_has_id_event_data_lines_and_schema_version(self) -> None:
        """The frame carries the cursor, type, and a v2-stamped JSON body."""
        envelope = make_envelope(
            "flow.run.started",
            tenant_id="default",
            partition_key="run-1",
            data=_SAMPLE_DATA["flow.run.started"],
        )
        frame = _format_sse_event("0", envelope)

        assert frame.startswith("id: 0\nevent: flow.run.started\ndata: ")
        assert frame.endswith("\n\n")
        payload = json.loads(frame.split("data: ", 1)[1].strip())
        assert payload["schemaVersion"] == SCHEMA_VERSION_V2
        assert payload["type"] == "flow.run.started"
        assert payload["partitionKey"] == "run-1"


class TestStreamEventsGenerator:
    """Direct, non-HTTP tests of ``_stream_events`` (see module docstring)."""

    def test_yields_backlog_in_order(self) -> None:
        """A fresh connection replays the whole partition, in cursor order."""

        async def run() -> list[str]:
            bus = InMemoryEventBus()
            run_id = "run-1"
            for type_ in ("flow.run.started", "run.step.started", "flow.run.completed"):
                _publish(bus, run_id, type_)
            agen = _stream_events(_FakeRequest(), bus, run_id, None, None)  # type: ignore[arg-type]
            return await _collect(agen, 3)

        frames = asyncio.run(run())

        assert len(frames) == 3
        assert frames[0].startswith("id: 0\nevent: flow.run.started\n")
        assert frames[1].startswith("id: 1\nevent: run.step.started\n")
        assert frames[2].startswith("id: 2\nevent: flow.run.completed\n")

    def test_resumes_strictly_after_cursor(self) -> None:
        """Resuming after cursor "0" replays only the later two events."""

        async def run() -> list[str]:
            bus = InMemoryEventBus()
            run_id = "run-1"
            for type_ in ("flow.run.started", "run.step.started", "flow.run.completed"):
                _publish(bus, run_id, type_)
            agen = _stream_events(_FakeRequest(), bus, run_id, "0", None)  # type: ignore[arg-type]
            return await _collect(agen, 2)

        frames = asyncio.run(run())

        assert len(frames) == 2
        assert "event: run.step.started" in frames[0]
        assert "event: flow.run.completed" in frames[1]

    def test_filters_by_type(self) -> None:
        """``types`` restricts delivery without disturbing cursor advancement."""

        async def run() -> list[str]:
            bus = InMemoryEventBus()
            run_id = "run-1"
            for type_ in ("flow.run.started", "run.step.started", "flow.run.completed"):
                _publish(bus, run_id, type_)
            agen = _stream_events(
                _FakeRequest(), bus, run_id, None, ("flow.run.completed",)  # type: ignore[arg-type]
            )
            return await _collect(agen, 1)

        frames = asyncio.run(run())

        assert len(frames) == 1
        assert "event: flow.run.completed" in frames[0]

    def test_stops_promptly_on_disconnect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The generator returns as soon as a disconnect poll reports True."""
        monkeypatch.setattr(runs_stream_v2, "DISCONNECT_POLL_INTERVAL_SEC", 0.01)

        async def run() -> list[str]:
            bus = InMemoryEventBus()
            run_id = "run-1"
            _publish(bus, run_id, "flow.run.started")
            request = _DisconnectingRequest(connected_polls=1)
            agen = _stream_events(request, bus, run_id, None, None)  # type: ignore[arg-type]
            return [frame async for frame in agen]

        frames = asyncio.run(run())

        assert len(frames) == 1
        assert "event: flow.run.started" in frames[0]

    def test_emits_heartbeat_when_idle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An idle live tail sends ``: ping`` once the heartbeat interval elapses."""
        monkeypatch.setattr(runs_stream_v2, "DISCONNECT_POLL_INTERVAL_SEC", 0.01)
        monkeypatch.setattr(runs_stream_v2, "HEARTBEAT_INTERVAL_SEC", 0.03)

        async def run() -> list[str]:
            bus = InMemoryEventBus()
            run_id = "run-1"
            _publish(bus, run_id, "flow.run.started")
            agen = _stream_events(_FakeRequest(), bus, run_id, None, None)  # type: ignore[arg-type]
            return await _collect(agen, 2)

        frames = asyncio.run(run())

        assert len(frames) == 2
        assert "event: flow.run.started" in frames[0]
        assert frames[1] == ": ping\n\n"

    def test_live_tail_delivers_events_published_after_subscribe(self) -> None:
        """A publish that happens after the stream starts is delivered live."""

        async def run() -> list[str]:
            bus = InMemoryEventBus()
            run_id = "run-1"
            agen = _stream_events(_FakeRequest(), bus, run_id, None, None)  # type: ignore[arg-type]

            async def _publish_soon() -> None:
                await asyncio.sleep(0.01)
                _publish(bus, run_id, "flow.run.started")

            publisher = asyncio.ensure_future(_publish_soon())
            try:
                return await _collect(agen, 1)
            finally:
                await publisher

        frames = asyncio.run(run())

        assert len(frames) == 1
        assert "event: flow.run.started" in frames[0]


class TestStreamRunEventsHandler:
    """Direct (non-HTTP) tests of ``stream_run_events``'s fast-fail paths."""

    def test_unknown_run_id_raises_404(self) -> None:
        """An unknown run id is rejected with a 404 before any streaming starts."""

        async def run() -> HTTPException:
            engine = _FakeEngine({})
            bus = InMemoryEventBus()
            with pytest.raises(HTTPException) as excinfo:
                await stream_run_events(
                    request=_FakeRequest(),  # type: ignore[arg-type]
                    run_id="missing",
                    cursor=None,
                    types=None,
                    tenant_id=None,
                    last_event_id=None,
                    engine=engine,  # type: ignore[arg-type]
                    bus=bus,
                )
            return excinfo.value

        error = asyncio.run(run())
        assert error.status_code == 404

    def test_tenant_mismatch_raises_404_not_403(self) -> None:
        """A ``?tenantId=`` mismatch reports 404, not 403 (no existence leak)."""

        async def run() -> HTTPException:
            engine = _FakeEngine({"run-1": _FakeRun(tenant_id="tenant-a")})
            bus = InMemoryEventBus()
            with pytest.raises(HTTPException) as excinfo:
                await stream_run_events(
                    request=_FakeRequest(),  # type: ignore[arg-type]
                    run_id="run-1",
                    cursor=None,
                    types=None,
                    tenant_id="tenant-b",
                    last_event_id=None,
                    engine=engine,  # type: ignore[arg-type]
                    bus=bus,
                )
            return excinfo.value

        error = asyncio.run(run())
        assert error.status_code == 404

    def test_invalid_types_filter_raises_400(self) -> None:
        """An uncataloged ``?types=`` entry is rejected with a 400."""

        async def run() -> HTTPException:
            engine = _FakeEngine({"run-1": _FakeRun(tenant_id="default")})
            bus = InMemoryEventBus()
            with pytest.raises(HTTPException) as excinfo:
                await stream_run_events(
                    request=_FakeRequest(),  # type: ignore[arg-type]
                    run_id="run-1",
                    cursor=None,
                    types="not.a.type",
                    tenant_id=None,
                    last_event_id=None,
                    engine=engine,  # type: ignore[arg-type]
                    bus=bus,
                )
            return excinfo.value

        error = asyncio.run(run())
        assert error.status_code == 400

    def test_matching_tenant_returns_streaming_response_with_backlog(self) -> None:
        """A valid request returns an SSE ``StreamingResponse`` over the backlog."""

        async def run() -> list[str]:
            engine = _FakeEngine({"run-1": _FakeRun(tenant_id="default")})
            bus = InMemoryEventBus()
            _publish(bus, "run-1", "flow.run.started")

            response = await stream_run_events(
                request=_FakeRequest(),  # type: ignore[arg-type]
                run_id="run-1",
                cursor=None,
                types=None,
                tenant_id="default",
                last_event_id=None,
                engine=engine,  # type: ignore[arg-type]
                bus=bus,
            )
            assert response.media_type == "text/event-stream"
            assert response.headers["cache-control"] == "no-cache"
            return await _collect(response.body_iterator, 1)  # type: ignore[arg-type]

        frames = asyncio.run(run())
        assert len(frames) == 1
        assert "event: flow.run.started" in frames[0]

    def test_last_event_id_header_wins_over_cursor_query(self) -> None:
        """``Last-Event-ID`` takes priority over ``?cursor=`` when both are sent."""

        async def run() -> list[str]:
            engine = _FakeEngine({"run-1": _FakeRun(tenant_id="default")})
            bus = InMemoryEventBus()
            for type_ in ("flow.run.started", "run.step.started", "flow.run.completed"):
                _publish(bus, "run-1", type_)

            response = await stream_run_events(
                request=_FakeRequest(),  # type: ignore[arg-type]
                run_id="run-1",
                cursor="0",
                types=None,
                tenant_id=None,
                last_event_id="1",
                engine=engine,  # type: ignore[arg-type]
                bus=bus,
            )
            return await _collect(response.body_iterator, 1)  # type: ignore[arg-type]

        frames = asyncio.run(run())
        assert len(frames) == 1
        assert "event: flow.run.completed" in frames[0]


class TestFlowRunEmitsCatalogEventSequence:
    """Emission-wiring test: a flow run publishes the expected event sequence."""

    def _skill_flow(self) -> dict[str, Any]:
        """A minimal single-skill flow manifest, mirroring ``test_flows_api.py``."""
        return {
            "schemaVersion": "1",
            "id": "autodev/flow-stream",
            "version": "1.0.0",
            "hostApi": ">=2.0 <3.0",
            "nodes": [{"id": "only", "type": "skill", "ref": "autodev/skill-echo"}],
            "edges": [],
        }

    def test_flow_run_publishes_started_step_and_completed_events(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``FlowEngine.start_run`` publishes the run's catalog events, in order.

        Covers the emission wiring added to ``backend/flows/engine.py`` and
        ``backend/flows/activation.py``: a completed single-skill run must
        publish ``flow.run.started``, ``run.step.started``,
        ``run.step.completed``, and ``flow.run.completed`` on the process
        event bus, in that order, all scoped to the run's own tenant and
        partition.
        """
        monkeypatch.delenv("AUTODEV_EVENT_BUS", raising=False)
        reset_event_bus_for_tests()
        try:
            store = SQLiteStore(f"sqlite:///{tmp_path / 'emission.db'}")
            callables = CallableRegistry()
            callables.register("autodev/skill-echo", lambda payload: {"echo": payload})
            engine = FlowEngine(
                store=store, handlers=build_default_handlers(callables=callables)
            )
            engine.registry.register_raw(self._skill_flow())

            run = engine.start_run("autodev/flow-stream", input={"x": 1})

            assert run.status == "completed"
            bus = get_event_bus()
            published = bus.replay(run.run_id)
            assert [envelope.type for envelope in published] == [
                "flow.run.started",
                "run.step.started",
                "run.step.completed",
                "flow.run.completed",
            ]
            assert all(envelope.tenantId == run.tenant_id for envelope in published)
            assert all(envelope.partitionKey == run.run_id for envelope in published)
        finally:
            reset_event_bus_for_tests()
