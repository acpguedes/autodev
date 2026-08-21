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


def _entry_sort_key(entry_id: str) -> tuple[int, int]:
    """Parse a fake stream entry id (``"N-0"``) into a numerically comparable key."""
    ms, _, seq = entry_id.partition("-")
    return (int(ms), int(seq or 0))


class _FakeRedisStreamClient:
    """In-memory stand-in for a Redis client, used to test :class:`RedisEventBus`."""

    def __init__(self) -> None:
        """Initialize empty in-memory streams."""
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

    def ping(self) -> bool:
        """Report the fake connection as always reachable."""
        return True

    def xadd(
        self,
        key: str,
        fields: dict[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = False,
    ) -> str:
        """Append an entry to an in-memory stream and return its id.

        When *maxlen* is given, trims the stream to its most recent
        *maxlen* entries — a simplified stand-in for Redis's ``MAXLEN ~``.
        """
        entries = self.streams.setdefault(key, [])
        entry_id = f"{len(entries) + 1}-0"
        entries.append((entry_id, dict(fields)))
        if maxlen is not None and len(entries) > maxlen:
            del entries[: len(entries) - maxlen]
        return entry_id

    def xrange(self, key: str, min: str = "-") -> list[tuple[str, dict[str, str]]]:
        """Return entries of an in-memory stream, oldest first.

        Args:
            key: Stream key.
            min: Redis ``XRANGE`` start bound — ``"-"`` for the beginning of
                the stream, ``"(<id>"`` for an exclusive start (matching
                :meth:`RedisEventBus.replay_from`'s cursor resume), or a bare
                id for an inclusive start.

        Returns:
            Matching entries, oldest first.
        """
        entries = self.streams.get(key, [])
        if min == "-":
            return list(entries)
        exclusive = min.startswith("(")
        bound = _entry_sort_key(min[1:] if exclusive else min)
        return [
            (entry_id, fields)
            for entry_id, fields in entries
            if _entry_sort_key(entry_id) > bound
            or (not exclusive and _entry_sort_key(entry_id) == bound)
        ]


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


def test_in_memory_bus_unsubscribe_stops_delivery() -> None:
    """The callable returned by ``subscribe`` removes that subscription."""
    bus = InMemoryEventBus()
    received: list[str] = []
    unsubscribe = bus.subscribe(WILDCARD, lambda e: received.append(e.eventId))

    bus.publish(_envelope())
    unsubscribe()
    bus.publish(_envelope())

    assert len(received) == 1


def test_in_memory_bus_unsubscribe_is_idempotent() -> None:
    """Calling the unsubscribe callable more than once is a no-op, not an error."""
    bus = InMemoryEventBus()
    unsubscribe = bus.subscribe(WILDCARD, lambda _e: None)

    unsubscribe()
    unsubscribe()


def test_in_memory_bus_unsubscribe_only_removes_its_own_subscription() -> None:
    """Unsubscribing one callback leaves other subscribers to the same type intact."""
    bus = InMemoryEventBus()
    received: list[str] = []
    unsubscribe_first = bus.subscribe(WILDCARD, lambda e: received.append(f"first:{e.eventId}"))
    bus.subscribe(WILDCARD, lambda e: received.append(f"second:{e.eventId}"))

    unsubscribe_first()
    event_id = bus.publish(_envelope())

    assert received == [f"second:{event_id}"]


def test_in_memory_bus_replay_from_unknown_partition_does_not_create_it() -> None:
    """Reading an unseen partition never grows the internal partition map (E45-S4)."""
    bus = InMemoryEventBus()

    assert bus.replay_from("never-seen", None) == []
    assert bus.replay("never-seen") == []

    assert "never-seen" not in bus._partitions  # noqa: SLF001


def test_in_memory_bus_trims_partition_past_max_size() -> None:
    """Publishing past ``max_partition_size`` drops the oldest entries, keeping cursors stable."""
    bus = InMemoryEventBus(max_partition_size=2)
    first, second, third = _envelope(), _envelope(), _envelope()
    for envelope in (first, second, third):
        bus.publish(envelope)

    full = bus.replay_from("run_1", None)
    assert [e.eventId for _cursor, e in full] == [second.eventId, third.eventId]

    # The surviving cursors are still the original sequence numbers ("1", "2"),
    # not renumbered from zero — resuming from a still-valid client cursor works.
    assert [cursor for cursor, _ in full] == ["1", "2"]
    assert bus.replay_from("run_1", "1") == [("2", third)]


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


def test_redis_bus_unsubscribe_stops_local_dispatch() -> None:
    """The callable returned by ``subscribe`` removes the in-process dispatch subscription."""
    client = _FakeRedisStreamClient()
    bus = RedisEventBus(client=client)
    received: list[str] = []
    unsubscribe = bus.subscribe(WILDCARD, lambda e: received.append(e.eventId))

    bus.publish(_envelope())
    unsubscribe()
    bus.publish(_envelope())

    assert len(received) == 1


def test_redis_bus_trims_stream_to_configured_maxlen() -> None:
    """Publishing past ``stream_maxlen`` trims the stream (E45-S4)."""
    client = _FakeRedisStreamClient()
    bus = RedisEventBus(client=client, stream_maxlen=2)
    for _ in range(3):
        bus.publish(_envelope())

    assert len(client.streams["autodev:events:run_1"]) == 2


def test_redis_bus_none_maxlen_disables_trimming() -> None:
    """``stream_maxlen=None`` never passes ``MAXLEN`` to ``XADD``."""
    client = _FakeRedisStreamClient()
    bus = RedisEventBus(client=client, stream_maxlen=None)
    for _ in range(5):
        bus.publish(_envelope())

    assert len(client.streams["autodev:events:run_1"]) == 5


def test_redis_bus_requires_client_or_url() -> None:
    """Constructing without a client or URL fails fast, matching Redis conventions."""
    with pytest.raises(ValueError):
        RedisEventBus()


def test_in_memory_replay_from_full_and_resumed() -> None:
    """``replay_from`` returns cursors, resumes exclusive of the given cursor, and empties past the end."""
    bus = InMemoryEventBus()
    first, second, third = _envelope(), _envelope(), _envelope()
    for envelope in (first, second, third):
        bus.publish(envelope)

    full = bus.replay_from("run_1", None)
    assert [cursor for cursor, _ in full] == ["0", "1", "2"]
    assert [e.eventId for _, e in full] == [first.eventId, second.eventId, third.eventId]

    resumed = bus.replay_from("run_1", full[0][0])
    assert [e.eventId for _, e in resumed] == [second.eventId, third.eventId]

    assert bus.replay_from("run_1", full[-1][0]) == []
    assert bus.replay_from("unknown_partition", None) == []


def test_redis_bus_replay_from_full_and_resumed() -> None:
    """The Redis bus's ``replay_from`` resumes past a given entry id via exclusive ``XRANGE``."""
    client = _FakeRedisStreamClient()
    bus = RedisEventBus(client=client)
    first, second, third = _envelope(), _envelope(), _envelope()
    for envelope in (first, second, third):
        bus.publish(envelope)

    full = bus.replay_from("run_1", None)
    cursors = [cursor for cursor, _ in full]
    assert [e.eventId for _, e in full] == [first.eventId, second.eventId, third.eventId]

    resumed = bus.replay_from("run_1", cursors[0])
    assert [e.eventId for _, e in resumed] == [second.eventId, third.eventId]

    assert bus.replay_from("run_1", cursors[-1]) == []
