"""Correlation identifiers and W3C execution-context propagation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
_CORRELATION_CARRIER_KEYS = {
    "request_id": "correlation_request_id",
    "run_id": "correlation_run_id",
    "step_id": "correlation_step_id",
    "tenant_id": "correlation_tenant_id",
}


@dataclass(frozen=True)
class CorrelationContext:
    """Bound domain identifiers that correlate traces, logs, and operations."""

    request_id: str = ""
    run_id: str = ""
    step_id: str = ""
    tenant_id: str = ""


_CURRENT_CORRELATION_CONTEXT: ContextVar[CorrelationContext] = ContextVar(
    "autodev_correlation_context", default=CorrelationContext()
)


def current_correlation_context() -> CorrelationContext:
    """Return the correlation context bound to the current execution context.

    Returns:
        The current immutable correlation context.
    """
    return _CURRENT_CORRELATION_CONTEXT.get()


def current_trace_id() -> str:
    """Return the active W3C trace id as 32 lowercase hexadecimal characters.

    Returns:
        The formatted trace id, or an empty string when no valid span is active.
    """
    span_context = trace.get_current_span().get_span_context()
    return f"{span_context.trace_id:032x}" if span_context.is_valid else ""


def current_span_id() -> str:
    """Return the active W3C span id as 16 lowercase hexadecimal characters.

    Returns:
        The formatted span id, or an empty string when no valid span is active.
    """
    span_context = trace.get_current_span().get_span_context()
    return f"{span_context.span_id:016x}" if span_context.is_valid else ""


def sanitize_identifier(value: str) -> str:
    """Normalize a bounded identifier or replace unsafe content with a digest.

    Args:
        value: Candidate correlation or telemetry identifier.

    Returns:
        A safe identifier, an empty string, or a stable SHA-256 prefix.
    """
    normalized = value.strip()
    if not normalized:
        return ""
    if _SAFE_IDENTIFIER.fullmatch(normalized):
        return normalized
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"sha256:{digest}"


@contextmanager
def bind_correlation_context(
    *,
    request_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    tenant_id: str | None = None,
) -> Iterator[CorrelationContext]:
    """Bind sanitized correlation fields while preserving unspecified parents.

    Args:
        request_id: Request identifier override, or ``None`` to inherit.
        run_id: Run identifier override, or ``None`` to inherit.
        step_id: Step identifier override, or ``None`` to inherit.
        tenant_id: Tenant identifier override, or ``None`` to inherit.

    Yields:
        The newly bound immutable correlation context.
    """
    parent = current_correlation_context()
    values = {
        "request_id": parent.request_id
        if request_id is None
        else sanitize_identifier(request_id),
        "run_id": parent.run_id if run_id is None else sanitize_identifier(run_id),
        "step_id": parent.step_id if step_id is None else sanitize_identifier(step_id),
        "tenant_id": parent.tenant_id
        if tenant_id is None
        else sanitize_identifier(tenant_id),
    }
    bound = CorrelationContext(**values)
    token = _CURRENT_CORRELATION_CONTEXT.set(bound)
    try:
        yield bound
    finally:
        _CURRENT_CORRELATION_CONTEXT.reset(token)


def capture_execution_context() -> dict[str, str]:
    """Capture W3C propagation headers and sanitized domain correlation fields.

    Returns:
        A serializable carrier safe for internal asynchronous hand-off.
    """
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    correlation = current_correlation_context()
    for field, key in _CORRELATION_CARRIER_KEYS.items():
        value = getattr(correlation, field)
        if value:
            carrier[key] = value
    return carrier


@contextmanager
def attach_execution_context(carrier: Mapping[str, str]) -> Iterator[None]:
    """Attach a captured W3C and domain execution context for a consumer.

    Args:
        carrier: Internal carrier returned by :func:`capture_execution_context`.

    Yields:
        Control while the extracted execution context is current.
    """
    parent_context = propagate.extract(carrier)
    token = otel_context.attach(parent_context)
    correlation = {
        field: carrier.get(key, "") for field, key in _CORRELATION_CARRIER_KEYS.items()
    }
    try:
        with bind_correlation_context(**correlation):
            yield
    finally:
        otel_context.detach(token)


__all__ = [
    "CorrelationContext",
    "attach_execution_context",
    "bind_correlation_context",
    "capture_execution_context",
    "current_correlation_context",
    "current_span_id",
    "current_trace_id",
    "sanitize_identifier",
]
