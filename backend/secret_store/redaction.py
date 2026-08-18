"""Exact-value secret redaction for logs, events, and artifacts (E33-S2-T2).

Two layers, by design:

- :class:`SecretRedactor` — an explicit, reference-attributed scrubber built
  from the exact set of values resolved for one environment provision
  (:mod:`backend.environments.manager`). Used where the caller needs to know
  *which* reference leaked (the E33-S2-T3 leak fixture) as well as scrub the
  text.
- The module-level registry (:func:`register_live_secret_value`/
  :func:`redact_event_data`) is a broader safety net: every value ever
  resolved in this process is scrubbed from every emitted event's payload
  (:func:`backend.events.runtime.emit_event`), not just the ones an
  environment provision produces directly -- this covers producers this
  module has no direct relationship with (e.g. ``run.timeline.*``).

Both layers do exact-value string replacement only. Entropy-based/heuristic
detection of *unknown* secret-shaped strings is explicitly out of scope
(documented limit, `docs/security/secrets.md`) -- only values this process
has actually resolved from the secret store are ever redacted.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from backend.secret_store.contracts import SecretReference

REDACTED_MARKER = "***REDACTED_SECRET***"

_registry_lock = threading.Lock()
_live_secret_values: set[str] = set()


def register_live_secret_value(value: str) -> None:
    """Record a resolved secret value as live -- scrubbed from every event henceforth.

    Args:
        value: The plaintext value to remember. A blank value is ignored
            (redacting the empty string would corrupt every payload).
    """
    if not value:
        return
    with _registry_lock:
        _live_secret_values.add(value)


def reset_registry_for_tests() -> None:
    """Clear the process-wide live-secret registry -- for use in test fixtures."""
    with _registry_lock:
        _live_secret_values.clear()


def _scrub(text: str, values: tuple[str, ...]) -> str:
    for value in values:
        if value in text:
            text = text.replace(value, REDACTED_MARKER)
    return text


def redact_event_data(data: dict) -> dict:  # type: ignore[type-arg]
    """Return a copy of an event's ``data`` payload with every live secret value scrubbed.

    Recurses into nested dicts/lists; every string leaf is checked. Called
    by :func:`backend.events.runtime.emit_event` for every event, so no
    individual producer needs to remember to redact its own payload.

    Args:
        data: The event's ``data`` payload, before validation/publish.

    Returns:
        An equivalent structure with every occurrence of a known live
        secret value replaced by :data:`REDACTED_MARKER`.
    """
    with _registry_lock:
        values = tuple(_live_secret_values)
    if not values:
        return data
    redacted = _redact_structure(data, values)
    assert isinstance(redacted, dict)
    return redacted


def _redact_structure(value: object, values: tuple[str, ...]) -> object:
    if isinstance(value, str):
        return _scrub(value, values)
    if isinstance(value, dict):
        return {key: _redact_structure(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_structure(item, values) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class SecretLeak:
    """One detected occurrence of a live secret value in scrubbed text.

    Attributes:
        reference: The secret whose value was found.
        location: Human-readable description of where it was found (e.g.
            an artifact key).
    """

    reference: SecretReference
    location: str


class SecretRedactor:
    """Scrubs and detects a fixed, reference-attributed set of live secret values."""

    def __init__(self, live_values: dict[str, SecretReference]) -> None:
        """Build a redactor over one environment provision's resolved secrets.

        Args:
            live_values: Mapping of plaintext value to the reference it was
                resolved from.
        """
        self._live_values = dict(live_values)

    def scrub(self, text: str) -> str:
        """Return *text* with every known live secret value replaced by the redaction marker."""
        return _scrub(text, tuple(self._live_values))

    def find_leaks(self, text: str, *, location: str) -> list[SecretLeak]:
        """Return every live secret reference whose value appears verbatim in *text*.

        Args:
            text: Unredacted text to scan (e.g. a task's stdout/diff).
            location: Human-readable description of where ``text`` came from.

        Returns:
            One :class:`SecretLeak` per matching reference.
        """
        return [
            SecretLeak(reference=reference, location=location)
            for value, reference in self._live_values.items()
            if value and value in text
        ]


__all__ = [
    "REDACTED_MARKER",
    "SecretLeak",
    "SecretRedactor",
    "redact_event_data",
    "register_live_secret_value",
    "reset_registry_for_tests",
]
