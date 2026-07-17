"""Process-wide Event Bus factory and best-effort emission helper (E9-S2-T2).

:func:`get_event_bus` builds (and caches) the single :class:`~backend.events.bus.EventBus`
instance every producer (the flow engine, the orchestrator, the SSE endpoint)
shares within a process, selected by ``autodev_event_bus`` in
:class:`~backend.config.settings.Settings` — mirroring the
``autodev_job_backend`` pattern in ``backend/coordination/redis.py``.

Unlike ``get_cache``/``get_lock_manager`` (which intentionally build a fresh,
uncached instance per call because their only caller does not need shared
state), the Event Bus **must** be a genuine singleton: publishers and the SSE
endpoint's live-tail subscriber only observe each other's events if they are
talking to the same in-process object. Hence the manual global-variable cache
(with a test-only reset hook), rather than deriving one fresh instance per
call.

:func:`emit_event` is the sanctioned way for producers to publish a cataloged
event: it builds the envelope via :func:`~backend.events.catalog.make_envelope`
and publishes it, but never lets a bus failure (a bad payload, a
disconnected Redis, ...) propagate into the caller — a run must never fail
*because* eventing failed. Failures are logged and swallowed.

When ``autodev_event_store_enabled`` is on (the default), the bus singleton
is built with a wildcard subscriber that durably appends every published
envelope to the State Store's Event Store (E8-S2). The subscriber path is
fault-isolated by the bus, so a persistence failure never blocks delivery
to other subscribers nor the publishing run.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config.settings import Settings, get_settings
from backend.events.bus import WILDCARD, EventBus, InMemoryEventBus, RedisEventBus
from backend.events.catalog import EventEnvelope, make_envelope
from backend.events.store import EventStore

logger = logging.getLogger(__name__)

_bus_instance: EventBus | None = None
_event_store_instance: EventStore | None = None


def get_event_store() -> EventStore:
    """Build and cache the process-wide :class:`EventStore` singleton.

    The instance is rebound automatically whenever the process durable store
    changes (e.g. after ``reset_store_cache()`` re-reads ``DATABASE_URL`` in
    tests), so a cached Event Store never outlives its backing database.

    Returns:
        The shared Event Store bound to the current process durable store.
    """
    global _event_store_instance
    from backend.persistence.database import get_store

    store = get_store()
    if _event_store_instance is None or _event_store_instance.backing_store is not store:
        _event_store_instance = EventStore(store)
    return _event_store_instance


def reset_event_store_for_tests() -> None:
    """Clear the cached Event Store singleton — for use in test fixtures."""
    global _event_store_instance
    _event_store_instance = None


def _persist_envelope(envelope: EventEnvelope) -> None:
    """Bus subscriber durably appending each published envelope (E8-S2-T1).

    Args:
        envelope: The envelope being delivered by the bus.
    """
    get_event_store().append(envelope)


def get_event_bus(settings: Settings | None = None) -> EventBus:
    """Build and cache the process-wide :class:`EventBus` singleton.

    Args:
        settings: Settings override; falls back to :func:`get_settings`. Only
            consulted the first time the singleton is built in a process (or
            after :func:`reset_event_bus_for_tests`).

    Returns:
        A :class:`~backend.events.bus.RedisEventBus` if ``autodev_event_bus``
        is ``"redis"``, else an
        :class:`~backend.events.bus.InMemoryEventBus`.
    """
    global _bus_instance
    if _bus_instance is None:
        active = settings or get_settings()
        if active.autodev_event_bus == "redis":
            _bus_instance = RedisEventBus(url=active.autodev_redis_url)
        else:
            _bus_instance = InMemoryEventBus()
        if active.autodev_event_store_enabled:
            _bus_instance.subscribe(WILDCARD, _persist_envelope)
    return _bus_instance


def reset_event_bus_for_tests() -> None:
    """Clear the cached Event Bus singleton — for use in test fixtures."""
    global _bus_instance
    _bus_instance = None


def emit_event(
    type_: str,
    *,
    tenant_id: str,
    partition_key: str,
    data: dict[str, Any],
    subject: dict[str, str] | None = None,
    trace_id: str = "",
    bus: EventBus | None = None,
) -> None:
    """Best-effort publish of a cataloged event; never raises.

    Builds the envelope via :func:`~backend.events.catalog.make_envelope` and
    publishes it to the process Event Bus. Any failure — an unknown event
    type, a schema-invalid payload, or a bus/transport error — is logged and
    swallowed so that a run's own execution is never disrupted by eventing.

    Args:
        type_: Event type; must exist in the catalog.
        tenant_id: Tenant emitting the event.
        partition_key: Ordering partition (typically the ``runId``).
        data: Payload; validated against the catalog's data model.
        subject: Identifiers of the affected resource(s).
        trace_id: W3C trace id propagated from the producing operation.
        bus: Event bus override; falls back to :func:`get_event_bus`.
    """
    try:
        envelope = make_envelope(
            type_,
            tenant_id=tenant_id,
            partition_key=partition_key,
            data=data,
            subject=subject,
            trace_id=trace_id,
        )
        (bus or get_event_bus()).publish(envelope)
    except Exception:  # noqa: BLE001 - eventing must never break a run
        logger.exception("Failed to emit event %s for partition %s", type_, partition_key)


__all__ = [
    "emit_event",
    "get_event_bus",
    "get_event_store",
    "reset_event_bus_for_tests",
    "reset_event_store_for_tests",
]
