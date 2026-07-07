"""Publish/subscribe and replay tests for the Event Bus backends (E9-S3-T2)."""

from __future__ import annotations

import pytest

from backend.events.bus import WILDCARD, InMemoryEventBus, RedisEventBus
from backend.events.catalog import EventEnvelope, make_envelope


def _envelope(type_: str = "run.step.started", partition: str = "run_1") -> EventEnvelope:
    """Build a small valid envelope for bus tests."""
    return make_envelope(
        type_,
        tenant_id="acme",
        partition_key=partition,
        data={"stepKey": "coder", "agent": "autodev/agent-coder"},
    )


class _FakeRedisStreamClient:
    """In-memory stand-in for a Redis client, used to test :class:`RedisEventBus`."""

    def __init__(self) -> None:
        """Initialize empty in-memory streams."""
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

    def ping(self) -> bool:
        """Report the fake connection as always reachable."""
        return True

    def xadd(self, key: str, fields: dict[str, str]) -> str:
        """Append an entry to an in-memory stream and return its id."""
        entries = self.streams.setdefault(key, [])
        entry_id = f"{len(entries) + 1}-0"
        entries.append((entry_id, dict(fields)))
        return entry_id

    def xrange(self, key: str) -> list[tuple[str, dict[str, str]]]:
        """Return all entries of an in-memory stream, oldest first."""
        return list(self.streams.get(key, []))


def test_in_memory_bus_dispatches_by_type_and_wildcard() -> None:
    """Subscribers receive matching types; wildcard receives everything else too."""
    bus = InMemoryEventBus()
    seen: list[str] = []
    bus.subscribe("run.step.started", lambda e: seen.append(f"typed:{e.eventId}"))
    bus.subscribe(WILDCARD, lambda e: seen.append(f"all:{e.eventId}"))
    bus.subscribe("flow.run.failed", lambda e: seen.append("wrong"))

    envelope = _envelope()
    event_id = bus.publish(envelope)

    assert event_id == envelope.eventId
    assert seen == [f"typed:{event_id}", f"all:{event_id}"]


def test_in_memory_bus_replays_partition_in_order() -> None:
    """Replay returns a partition's events in publish order, isolated per partition."""
    bus = InMemoryEventBus()
    first, second, other = _envelope(), _envelope(), _envelope(partition="run_2")
    for envelope in (first, second, other):
        bus.publish(envelope)

    assert [e.eventId for e in bus.replay("run_1")] == [first.eventId, second.eventId]
    assert [e.eventId for e in bus.replay("run_2")] == [other.eventId]


def test_failing_subscriber_does_not_block_delivery() -> None:
    """A raising subscriber is isolated; later subscribers still receive the event."""
    bus = InMemoryEventBus()

    def _boom(_: EventEnvelope) -> None:
        raise RuntimeError("subscriber crash")

    received: list[str] = []
    bus.subscribe(WILDCARD, _boom)
    bus.subscribe(WILDCARD, lambda e: received.append(e.eventId))

    event_id = bus.publish(_envelope())

    assert received == [event_id]


def test_redis_bus_persists_to_partition_stream_and_replays() -> None:
    """The Redis bus appends the JSON envelope per partition and replays it intact."""
    client = _FakeRedisStreamClient()
    bus = RedisEventBus(client=client)
    received: list[str] = []
    bus.subscribe("run.step.started", lambda e: received.append(e.eventId))

    envelope = _envelope()
    bus.publish(envelope)

    assert received == [envelope.eventId]
    assert list(client.streams) == ["autodev:events:run_1"]
    replayed = bus.replay("run_1")
    assert [e.model_dump() for e in replayed] == [envelope.model_dump()]


def test_redis_bus_requires_client_or_url() -> None:
    """Constructing without a client or URL fails fast, matching Redis conventions."""
    with pytest.raises(ValueError):
        RedisEventBus()
