"""Event catalog and Event Bus for the v2 platform (E9-S3, reference §14.5)."""

from backend.events.bus import EventBus, InMemoryEventBus, RedisEventBus
from backend.events.catalog import (
    EVENT_CATALOG,
    SCHEMA_VERSION_EVENTS,
    EventDefinition,
    EventEnvelope,
    is_compatible_evolution,
    make_envelope,
)

__all__ = [
    "EVENT_CATALOG",
    "SCHEMA_VERSION_EVENTS",
    "EventBus",
    "EventDefinition",
    "EventEnvelope",
    "InMemoryEventBus",
    "RedisEventBus",
    "is_compatible_evolution",
    "make_envelope",
]
