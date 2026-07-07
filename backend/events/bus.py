"""Event Bus with in-memory and Redis Streams backends (E9-S3-T2, §14.5).

Delivery is **at-least-once**; consumers must be idempotent by ``eventId``.
Ordering is guaranteed **per partition key** (one Redis stream / in-memory
list per partition), not globally. A subscriber that raises does not block
delivery to the remaining subscribers (resilient delivery, E9-S3 CNF).
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
        envelopes: list[EventEnvelope] = []
        for _entry_id, fields in entries:
            raw = fields.get(b"envelope") or fields.get("envelope")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            envelopes.append(EventEnvelope.model_validate(json.loads(raw)))
        return envelopes


__all__ = ["EventBus", "InMemoryEventBus", "RedisEventBus", "Subscriber", "WILDCARD"]
