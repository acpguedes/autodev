"""Event Bus with in-memory and Redis Streams backends (E9-S2-T1, E9-S3-T2, §14.5).

Delivery is **at-least-once**; consumers must be idempotent by ``eventId``.
Ordering is guaranteed **per partition key** (one Redis stream / in-memory
list per partition), not globally. A subscriber that raises does not block
delivery to the remaining subscribers (resilient delivery, E9-S3 CNF).

:meth:`EventBus.replay_from` (E9-S2-T1) adds cursor-aware replay on top of
:meth:`EventBus.replay`: it returns each envelope paired with an opaque,
backend-specific cursor, and accepts an ``after_cursor`` exclusive-start
position so a consumer (e.g. the ``/v2/runs/{run_id}/events/stream`` SSE
endpoint) can resume exactly where it left off after a reconnect.
"""

from __future__ import annotations

from collections import defaultdict
import json
import logging
from typing import Any, Callable, Protocol

from backend.events.catalog import EventEnvelope

logger = logging.getLogger(__name__)

Subscriber = Callable[[EventEnvelope], None]
"""Callback invoked synchronously with each published envelope."""

WILDCARD = "*"
"""Subscription key matching every event type."""


def _stream_key(partition_key: str) -> str:
    """Build the namespaced Redis stream key for a partition.

    Args:
        partition_key: Envelope ``partitionKey`` (typically a ``runId``).

    Returns:
        The fully qualified stream key.
    """
    return f"autodev:events:{partition_key}"


class EventBus(Protocol):
    """Publish/subscribe contract shared by every bus backend."""

    def publish(self, envelope: EventEnvelope) -> str:
        """Persist and fan out an envelope; returns its ``eventId``."""
        ...

    def subscribe(self, type_: str, subscriber: Subscriber) -> None:
        """Register a callback for a type (or :data:`WILDCARD`)."""
        ...

    def replay(self, partition_key: str) -> list[EventEnvelope]:
        """Return every stored envelope of a partition, in publish order."""
        ...

    def replay_from(
        self, partition_key: str, after_cursor: str | None
    ) -> list[tuple[str, EventEnvelope]]:
        """Return a partition's envelopes strictly after a cursor, with cursors."""
        ...


class _SubscriberRegistry:
    """Shared subscriber bookkeeping and fault-isolated dispatch."""

    def __init__(self) -> None:
        """Initialize an empty type-to-subscribers index."""
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)

    def subscribe(self, type_: str, subscriber: Subscriber) -> None:
        """Register a callback for an event type.

        Args:
            type_: Catalog event type, or :data:`WILDCARD` for all types.
            subscriber: Callback receiving each matching envelope.
        """
        self._subscribers[type_].append(subscriber)

    def dispatch(self, envelope: EventEnvelope) -> None:
        """Invoke matching subscribers, isolating individual failures.

        Args:
            envelope: The envelope being delivered.
        """
        for subscriber in self._subscribers[envelope.type] + self._subscribers[WILDCARD]:
            try:
                subscriber(envelope)
            except Exception:  # noqa: BLE001 - resilient delivery (E9-S3 CNF)
                logger.exception("Event subscriber failed for %s", envelope.eventId)


class InMemoryEventBus:
    """In-process bus used locally and in tests (no broker required)."""

    def __init__(self) -> None:
        """Initialize empty partitions and subscribers."""
        self._registry = _SubscriberRegistry()
        self._partitions: dict[str, list[EventEnvelope]] = defaultdict(list)

    def publish(self, envelope: EventEnvelope) -> str:
        """Append the envelope to its partition and dispatch subscribers.

        Args:
            envelope: Validated envelope from ``make_envelope``.

        Returns:
            The envelope's ``eventId``.
        """
        self._partitions[envelope.partitionKey].append(envelope)
        self._registry.dispatch(envelope)
        return envelope.eventId

    def subscribe(self, type_: str, subscriber: Subscriber) -> None:
        """Register a callback for a type (or :data:`WILDCARD`)."""
        self._registry.subscribe(type_, subscriber)

    def replay(self, partition_key: str) -> list[EventEnvelope]:
        """Return the partition's envelopes in publish order.

        Args:
            partition_key: Partition to replay.

        Returns:
            Stored envelopes, oldest first.
        """
        return list(self._partitions[partition_key])

    def replay_from(
        self, partition_key: str, after_cursor: str | None
    ) -> list[tuple[str, EventEnvelope]]:
        """Return a partition's envelopes strictly after a cursor.

        The cursor is the envelope's zero-based position within the
        partition's append-only list, stringified (``"0"``, ``"1"``, ...).

        Args:
            partition_key: Partition to replay.
            after_cursor: Exclusive-start cursor; ``None`` replays from the
                beginning of the partition.

        Returns:
            Ordered ``(cursor, envelope)`` pairs for events strictly after
            ``after_cursor``.
        """
        envelopes = self._partitions[partition_key]
        start = int(after_cursor) + 1 if after_cursor is not None else 0
        return [(str(index), envelopes[index]) for index in range(start, len(envelopes))]


class RedisEventBus:
    """Redis Streams-backed bus: durable, replayable, ordered per partition."""

    def __init__(self, *, client: Any | None = None, url: str = "") -> None:
        """Initialize the bus, connecting to Redis and verifying reachability.

        Args:
            client: Pre-built Redis client to reuse; a new one is built if omitted.
            url: Redis connection URL, used when ``client`` is omitted.

        Raises:
            RuntimeError: If the ``redis`` package is not installed.
            ValueError: If ``client`` is omitted and ``url`` is blank.
        """
        if client is None:
            from backend.coordination.redis import _redis_client_from_url

            client = _redis_client_from_url(url)
        self._client = client
        self._client.ping()
        self._registry = _SubscriberRegistry()

    def publish(self, envelope: EventEnvelope) -> str:
        """Append the envelope to its partition stream and dispatch locally.

        Cross-process consumers read the stream; in-process subscribers are
        dispatched synchronously after the append (at-least-once).

        Args:
            envelope: Validated envelope from ``make_envelope``.

        Returns:
            The envelope's ``eventId``.
        """
        self._client.xadd(
            _stream_key(envelope.partitionKey),
            {"envelope": envelope.model_dump_json()},
        )
        self._registry.dispatch(envelope)
        return envelope.eventId

    def subscribe(self, type_: str, subscriber: Subscriber) -> None:
        """Register a callback for a type (or :data:`WILDCARD`)."""
        self._registry.subscribe(type_, subscriber)

    def replay(self, partition_key: str) -> list[EventEnvelope]:
        """Read back a partition's stream, oldest first.

        Args:
            partition_key: Partition to replay.

        Returns:
            Stored envelopes, in stream order.
        """
        entries = self._client.xrange(_stream_key(partition_key))
        return [_decode_entry(fields) for _entry_id, fields in entries]

    def replay_from(
        self, partition_key: str, after_cursor: str | None
    ) -> list[tuple[str, EventEnvelope]]:
        """Return a partition stream's entries strictly after a cursor.

        The cursor is the Redis stream entry id (e.g. ``"1699999999999-0"``).
        Resuming uses ``XRANGE``'s exclusive-start syntax (``(id``) so the
        cursor entry itself is never re-delivered.

        Args:
            partition_key: Partition to replay.
            after_cursor: Exclusive-start stream entry id; ``None`` replays
                from the beginning of the stream.

        Returns:
            Ordered ``(entry_id, envelope)`` pairs for entries strictly after
            ``after_cursor``.
        """
        start = f"({after_cursor}" if after_cursor is not None else "-"
        entries = self._client.xrange(_stream_key(partition_key), min=start)
        result: list[tuple[str, EventEnvelope]] = []
        for entry_id, fields in entries:
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode("utf-8")
            result.append((entry_id, _decode_entry(fields)))
        return result


def _decode_entry(fields: dict[Any, Any]) -> EventEnvelope:
    """Decode a Redis stream entry's fields back into an :class:`EventEnvelope`.

    Args:
        fields: The entry's field map, as returned by ``XADD``/``XRANGE``
            (keys and values may be ``str`` or ``bytes`` depending on the
            client's ``decode_responses`` setting).

    Returns:
        The decoded envelope.
    """
    raw = fields.get(b"envelope") or fields.get("envelope")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        raise ValueError(f"missing or invalid 'envelope' field in stream entry: {fields!r}")
    return EventEnvelope.model_validate(json.loads(raw))


__all__ = ["EventBus", "InMemoryEventBus", "RedisEventBus", "Subscriber", "WILDCARD"]
