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


Unsubscribe = Callable[[], None]
"""Cancellation token returned by :meth:`EventBus.subscribe` (E45-S3)."""


class EventBus(Protocol):
    """Publish/subscribe contract shared by every bus backend."""

    def publish(self, envelope: EventEnvelope) -> str:
        """Persist and fan out an envelope; returns its ``eventId``."""
        ...

    def subscribe(self, type_: str, subscriber: Subscriber) -> Unsubscribe:
        """Register a callback for a type (or :data:`WILDCARD`).

        Returns:
            A zero-argument callable that removes this subscription;
            idempotent (calling it more than once is a no-op after the
            first call).
        """
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

    def subscribe(self, type_: str, subscriber: Subscriber) -> Unsubscribe:
        """Register a callback for an event type.

        Args:
            type_: Catalog event type, or :data:`WILDCARD` for all types.
            subscriber: Callback receiving each matching envelope.

        Returns:
            An idempotent callable that removes this subscription.
        """
        self._subscribers[type_].append(subscriber)

        def _unsubscribe() -> None:
            try:
                self._subscribers[type_].remove(subscriber)
            except ValueError:
                pass

        return _unsubscribe

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


_DEFAULT_MAX_PARTITION_SIZE = 10_000
"""Default cap on retained envelopes per in-memory partition (E45-S4)."""


class InMemoryEventBus:
    """In-process bus used locally and in tests (no broker required)."""

    def __init__(self, *, max_partition_size: int | None = _DEFAULT_MAX_PARTITION_SIZE) -> None:
        """Initialize empty partitions and subscribers.

        Args:
            max_partition_size: Maximum envelopes retained per partition;
                oldest entries are dropped once exceeded. ``None`` disables
                trimming. Cursors are a monotonically increasing per-partition
                sequence number (not a raw list index), so they remain valid
                across trims.
        """
        self._registry = _SubscriberRegistry()
        self._partitions: dict[str, list[tuple[int, EventEnvelope]]] = defaultdict(list)
        self._next_seq: dict[str, int] = defaultdict(int)
        self._max_partition_size = max_partition_size

    def publish(self, envelope: EventEnvelope) -> str:
        """Append the envelope to its partition and dispatch subscribers.

        Trims the partition to :attr:`_max_partition_size` afterward,
        dropping the oldest entries first — the durable Event Store (E8-S2)
        remains the source of record, so this bus is transport only.

        Args:
            envelope: Validated envelope from ``make_envelope``.

        Returns:
            The envelope's ``eventId``.
        """
        partition_key = envelope.partitionKey
        seq = self._next_seq[partition_key]
        self._next_seq[partition_key] = seq + 1
        partition = self._partitions[partition_key]
        partition.append((seq, envelope))
        if self._max_partition_size is not None and len(partition) > self._max_partition_size:
            del partition[: len(partition) - self._max_partition_size]
        self._registry.dispatch(envelope)
        return envelope.eventId

    def subscribe(self, type_: str, subscriber: Subscriber) -> Unsubscribe:
        """Register a callback for a type (or :data:`WILDCARD`)."""
        return self._registry.subscribe(type_, subscriber)

    def replay(self, partition_key: str) -> list[EventEnvelope]:
        """Return the partition's envelopes in publish order.

        Args:
            partition_key: Partition to replay.

        Returns:
            Stored envelopes, oldest first (within the retained window).
        """
        return [envelope for _seq, envelope in self._partitions.get(partition_key, [])]

    def replay_from(
        self, partition_key: str, after_cursor: str | None
    ) -> list[tuple[str, EventEnvelope]]:
        """Return a partition's envelopes strictly after a cursor.

        The cursor is the envelope's per-partition sequence number,
        stringified (``"0"``, ``"1"``, ...) — stable across trimming, unlike
        a raw list index. Reading an unknown partition never creates one
        (E45-S4): it returns an empty list without touching the partition
        map.

        Args:
            partition_key: Partition to replay.
            after_cursor: Exclusive-start cursor; ``None`` replays from the
                beginning of the retained window.

        Returns:
            Ordered ``(cursor, envelope)`` pairs for events strictly after
            ``after_cursor``.
        """
        start_seq = int(after_cursor) + 1 if after_cursor is not None else 0
        return [
            (str(seq), envelope)
            for seq, envelope in self._partitions.get(partition_key, [])
            if seq >= start_seq
        ]


_DEFAULT_STREAM_MAXLEN = 10_000
"""Default ``XADD MAXLEN ~`` cap applied per partition stream (E45-S4)."""


class RedisEventBus:
    """Redis Streams-backed bus: durable, replayable, ordered per partition."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        url: str = "",
        stream_maxlen: int | None = _DEFAULT_STREAM_MAXLEN,
    ) -> None:
        """Initialize the bus, connecting to Redis and verifying reachability.

        Args:
            client: Pre-built Redis client to reuse; a new one is built if omitted.
            url: Redis connection URL, used when ``client`` is omitted.
            stream_maxlen: Approximate cap (``XADD MAXLEN ~``) applied to
                each partition stream on publish; ``None`` disables trimming.
                The durable Event Store (E8-S2) remains the source of
                record, so trimming the bus stream loses nothing durable —
                replay older than the retained window degrades explicitly
                (fewer/no entries returned).

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
        self._stream_maxlen = stream_maxlen

    def publish(self, envelope: EventEnvelope) -> str:
        """Append the envelope to its partition stream and dispatch locally.

        Cross-process consumers read the stream; in-process subscribers are
        dispatched synchronously after the append (at-least-once).

        Args:
            envelope: Validated envelope from ``make_envelope``.

        Returns:
            The envelope's ``eventId``.
        """
        if self._stream_maxlen is not None:
            self._client.xadd(
                _stream_key(envelope.partitionKey),
                {"envelope": envelope.model_dump_json()},
                maxlen=self._stream_maxlen,
                approximate=True,
            )
        else:
            self._client.xadd(
                _stream_key(envelope.partitionKey),
                {"envelope": envelope.model_dump_json()},
            )
        self._registry.dispatch(envelope)
        return envelope.eventId

    def subscribe(self, type_: str, subscriber: Subscriber) -> Unsubscribe:
        """Register a callback for a type (or :data:`WILDCARD`)."""
        return self._registry.subscribe(type_, subscriber)

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


__all__ = [
    "EventBus",
    "InMemoryEventBus",
    "RedisEventBus",
    "Subscriber",
    "Unsubscribe",
    "WILDCARD",
]
