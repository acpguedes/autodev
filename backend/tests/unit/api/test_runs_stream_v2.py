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
import contextlib
import json
import time
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
from backend.auth.contracts import AuthMethod, PrincipalV2, Role
from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.events.bus import WILDCARD, EventBus, InMemoryEventBus
from backend.events.catalog import make_envelope
from backend.events.runtime import (
    get_event_bus,
    get_event_store,
    reset_event_bus_for_tests,
    reset_event_store_for_tests,
)
from backend.flows.engine import FlowEngine
from backend.flows.handlers import CallableRegistry, build_default_handlers
from backend.persistence.database import reset_store_cache
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
class _FakeProjection:
    """Minimal stand-in for :class:`~backend.events.records.EventProjection`."""

    tenant_id: str


class _FakeEventStore:
    """Minimal stand-in for :class:`~backend.events.store.EventStore`.

    ``stream_run_events`` only ever touches ``event_store.get_projection(run_id)``
    for its existence/tenant check (E42-S1), so a real event store (and its
    database) is unnecessary for handler-level tests.
    """

    def __init__(self, projections: dict[str, _FakeProjection]) -> None:
        """Store the fixed run-id to projection mapping."""
        self._projections = projections

    def get_projection(self, run_id: str) -> _FakeProjection | None:
        """Look up a run's projection by id, or ``None`` if unknown."""
        return self._projections.get(run_id)


def _principal(tenant_id: str) -> PrincipalV2:
    """Build a minimal authenticated principal scoped to *tenant_id*."""
    return PrincipalV2(
        subject="user-1",
        tenant_id=tenant_id,
        roles=(Role.VIEWER,),
        scopes=frozenset(),
        auth_method=AuthMethod.OIDC,
    )


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


    def test_replay_from_is_offloaded_and_does_not_block_the_event_loop(self) -> None:
        """A slow, blocking ``replay_from`` runs off the event loop (E45-S4-T1)."""

        class _SlowReplayBus:
            """Bus stand-in whose ``replay_from`` blocks synchronously."""

            def subscribe(self, _type: str, _subscriber: Any) -> Any:
                """Return a no-op unsubscribe token."""
                return lambda: None

            def replay_from(self, _run_id: str, _cursor: Any) -> list[Any]:
                """Block the calling thread, simulating a slow synchronous XRANGE."""
                time.sleep(0.05)
                return []

        async def run() -> bool:
            bus = _SlowReplayBus()
            agen = _stream_events(_FakeRequest(), bus, "run-1", None, None)  # type: ignore[arg-type]
            ticked = False

            async def _tick() -> None:
                nonlocal ticked
                await asyncio.sleep(0.01)
                ticked = True

            replay_task = asyncio.ensure_future(agen.__anext__())
            tick_task = asyncio.ensure_future(_tick())
            await asyncio.sleep(0.02)
            await tick_task
            replay_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await replay_task
            await agen.aclose()  # type: ignore[attr-defined]
            return ticked

        assert asyncio.run(run())

    def test_unsubscribes_on_disconnect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Disconnect leaves zero subscribers registered on the bus (E45-S3)."""
        monkeypatch.setattr(runs_stream_v2, "DISCONNECT_POLL_INTERVAL_SEC", 0.01)

        async def run() -> int:
            bus = InMemoryEventBus()
            run_id = "run-1"
            _publish(bus, run_id, "flow.run.started")
            request = _DisconnectingRequest(connected_polls=1)
            agen = _stream_events(request, bus, run_id, None, None)  # type: ignore[arg-type]
            async for _frame in agen:
                pass
            return len(bus._registry._subscribers[WILDCARD])  # noqa: SLF001

        remaining = asyncio.run(run())

        assert remaining == 0

    def test_unsubscribes_when_generator_is_cancelled(self) -> None:
        """A cancelled generator (client abort mid-wait) also unsubscribes cleanly."""

        async def run() -> int:
            bus = InMemoryEventBus()
            run_id = "run-1"
            agen = _stream_events(_FakeRequest(), bus, run_id, None, None)  # type: ignore[arg-type]
            task = asyncio.ensure_future(agen.__anext__())
            await asyncio.sleep(0.01)
            task.cancel()
            # The generator's own `except CancelledError: return` swallows the
            # cancellation and completes normally (StopAsyncIteration from
            # __anext__), rather than the task ending in "cancelled" state —
            # its `finally: unsubscribe()` still runs either way.
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await task
            await agen.aclose()  # type: ignore[attr-defined]
            return len(bus._registry._subscribers[WILDCARD])  # noqa: SLF001

        remaining = asyncio.run(run())

        assert remaining == 0


class TestStreamRunEventsHandler:
    """Direct (non-HTTP) tests of ``stream_run_events``'s fast-fail paths."""

    def test_unknown_run_id_raises_404(self) -> None:
        """An unknown run id is rejected with a 404 before any streaming starts."""

        async def run() -> HTTPException:
            event_store = _FakeEventStore({})
            bus = InMemoryEventBus()
            with pytest.raises(HTTPException) as excinfo:
                await stream_run_events(
                    request=_FakeRequest(),  # type: ignore[arg-type]
                    run_id="missing",
                    cursor=None,
                    types=None,
                    tenant_id=None,
                    last_event_id=None,
                    event_store=event_store,  # type: ignore[arg-type]
                    bus=bus,
                    principal=_principal("default"),
                )
            return excinfo.value

        error = asyncio.run(run())
        assert error.status_code == 404

    def test_run_owned_by_another_tenant_raises_404_not_403(self) -> None:
        """A run owned by another tenant is a 404, not a 403 (no existence leak).

        Enforced purely from ``principal.tenant_id`` (ADR-019/E11-S3) — the
        caller never supplies which tenant to scope to.
        """

        async def run() -> HTTPException:
            event_store = _FakeEventStore({"run-1": _FakeProjection(tenant_id="tenant-a")})
            bus = InMemoryEventBus()
            with pytest.raises(HTTPException) as excinfo:
                await stream_run_events(
                    request=_FakeRequest(),  # type: ignore[arg-type]
                    run_id="run-1",
                    cursor=None,
                    types=None,
                    tenant_id=None,
                    last_event_id=None,
                    event_store=event_store,  # type: ignore[arg-type]
                    bus=bus,
                    principal=_principal("tenant-b"),
                )
            return excinfo.value

        error = asyncio.run(run())
        assert error.status_code == 404

    def test_tenant_id_query_param_disagreeing_with_principal_raises_404(self) -> None:
        """A ``?tenantId=`` that disagrees with the caller's own tenant is a 404.

        The query parameter is only a redundant consistency check against
        ``principal.tenant_id`` — it can never select or widen scope.
        """

        async def run() -> HTTPException:
            event_store = _FakeEventStore({"run-1": _FakeProjection(tenant_id="tenant-a")})
            bus = InMemoryEventBus()
            with pytest.raises(HTTPException) as excinfo:
                await stream_run_events(
                    request=_FakeRequest(),  # type: ignore[arg-type]
                    run_id="run-1",
                    cursor=None,
                    types=None,
                    tenant_id="tenant-b",
                    last_event_id=None,
                    event_store=event_store,  # type: ignore[arg-type]
                    bus=bus,
                    principal=_principal("tenant-a"),
                )
            return excinfo.value

        error = asyncio.run(run())
        assert error.status_code == 404

    def test_invalid_types_filter_raises_400(self) -> None:
        """An uncataloged ``?types=`` entry is rejected with a 400."""

        async def run() -> HTTPException:
            event_store = _FakeEventStore({"run-1": _FakeProjection(tenant_id="default")})
            bus = InMemoryEventBus()
            with pytest.raises(HTTPException) as excinfo:
                await stream_run_events(
                    request=_FakeRequest(),  # type: ignore[arg-type]
                    run_id="run-1",
                    cursor=None,
                    types="not.a.type",
                    tenant_id=None,
                    last_event_id=None,
                    event_store=event_store,  # type: ignore[arg-type]
                    bus=bus,
                    principal=_principal("default"),
                )
            return excinfo.value

        error = asyncio.run(run())
        assert error.status_code == 400

    def test_matching_tenant_returns_streaming_response_with_backlog(self) -> None:
        """A valid request returns an SSE ``StreamingResponse`` over the backlog."""

        async def run() -> list[str]:
            event_store = _FakeEventStore({"run-1": _FakeProjection(tenant_id="default")})
            bus = InMemoryEventBus()
            _publish(bus, "run-1", "flow.run.started")

            response = await stream_run_events(
                request=_FakeRequest(),  # type: ignore[arg-type]
                run_id="run-1",
                cursor=None,
                types=None,
                tenant_id="default",
                last_event_id=None,
                event_store=event_store,  # type: ignore[arg-type]
                bus=bus,
                principal=_principal("default"),
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
            event_store = _FakeEventStore({"run-1": _FakeProjection(tenant_id="default")})
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
                event_store=event_store,  # type: ignore[arg-type]
                bus=bus,
                principal=_principal("default"),
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


class TestChatTriggeredRunResolvesOnStream:
    """A Chat-triggered run's ``run_id`` resolves on the SSE endpoint (E42-S1-T3).

    Regression test for the root cause: ``stream_run_events`` used to check
    only the Flow Engine's own run store, so every Orchestrator/Chat run
    404d here even though its events were already on the bus. Drives a real
    turn through the actual ``/v2`` HTTP surface (mirroring
    ``test_chat_timeline_v2.py``'s fixture), then calls
    ``stream_run_events`` directly on the resulting ``turnId`` — bypassing
    HTTP for the GET only because ``TestClient`` cannot exercise the
    live-tail generator (see module docstring) — and asserts it resolves
    instead of raising a 404.
    """

    def test_turn_created_via_http_resolves_on_stream(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'v2-chat-stream.db'}")
        monkeypatch.setenv("LLM_PROVIDER", "stub")
        monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
        reset_runtime_config_cache()
        reset_settings_cache()
        reset_store_cache()
        reset_event_bus_for_tests()
        reset_event_store_for_tests()
        from backend.llm.factory import get_chat_model

        get_chat_model.cache_clear()
        from fastapi.testclient import TestClient

        from backend.api.main import app

        try:
            with TestClient(app) as client:
                session = client.post("/v2/sessions", json={"goal": "Ship the E42-S1 fix"})
                assert session.status_code == 201, session.text
                session_id = session.json()["session_id"]

                turn = client.post(
                    f"/v2/sessions/{session_id}/turns", json={"message": "Please proceed"}
                )
                assert turn.status_code == 201, turn.text
                run_id = turn.json()["turnId"]

            async def run() -> Any:
                return await stream_run_events(
                    request=_FakeRequest(),  # type: ignore[arg-type]
                    run_id=run_id,
                    cursor=None,
                    types=None,
                    tenant_id=None,
                    last_event_id=None,
                    event_store=get_event_store(),
                    bus=get_event_bus(),
                    principal=_principal("default"),
                )

            response = asyncio.run(run())
            assert response.media_type == "text/event-stream"

            async def collect() -> list[str]:
                return await _collect(response.body_iterator, 2)  # type: ignore[arg-type]

            frames = asyncio.run(collect())
            assert any("event: flow.run.started" in frame for frame in frames)
        finally:
            app.dependency_overrides.clear()
            reset_store_cache()
            reset_runtime_config_cache()
            reset_settings_cache()
            reset_event_bus_for_tests()
            reset_event_store_for_tests()
            get_chat_model.cache_clear()
