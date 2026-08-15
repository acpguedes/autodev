"""Structured JSON logging with shared correlation and redaction."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from backend.observability.context import (
    current_correlation_context,
    current_span_id,
    current_trace_id,
    sanitize_identifier,
)

_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
    "access_key",
    "private_key",
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_API_KEY_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|token|secret|password)"
    r"\s*[:=]\s*[^\s,;]+"
)
_COMMON_API_KEY_PATTERN = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|AIza[A-Za-z0-9_-]{20,})\b"
)
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_OPERATIONAL_EXTRAS = (
    "event",
    "method",
    "route",
    "status",
    "duration_s",
    "error_code",
)
_CORRELATION_FIELDS = ("request_id", "run_id", "step_id", "tenant_id")


def _is_sensitive_key(key: object) -> bool:
    """Return whether a mapping or record key denotes secret material.

    Args:
        key: Candidate key.

    Returns:
        ``True`` when the normalized key contains a sensitive fragment.
    """
    normalized = str(key).casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_string(value: str) -> str:
    """Redact credentials and email addresses embedded in text.

    Args:
        value: Arbitrary log text.

    Returns:
        Redacted text safe for operational telemetry.
    """
    redacted = _BEARER_PATTERN.sub(f"Bearer {_REDACTED}", value)
    redacted = _API_KEY_PATTERN.sub(
        lambda match: f"{match.group(1)}={_REDACTED}", redacted
    )
    redacted = _COMMON_API_KEY_PATTERN.sub(_REDACTED, redacted)
    return _EMAIL_PATTERN.sub(_REDACTED, redacted)


def redact_telemetry_value(value: Any, *, key: object | None = None) -> Any:
    """Recursively redact a value using its containing key when available.

    Args:
        value: Scalar or nested structured value.
        key: Optional mapping or record key associated with the value.

    Returns:
        A recursively redacted value preserving safe container shapes.
    """
    if key is not None and _is_sensitive_key(key):
        return _REDACTED
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, Mapping):
        return {
            item_key: redact_telemetry_value(item_value, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact_telemetry_value(item) for item in value)
    if isinstance(value, list):
        return [redact_telemetry_value(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact_telemetry_value(item) for item in value]
    return value


class TelemetryRedactionFilter(logging.Filter):
    """Mutate a log record once so every downstream handler sees safe data."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact record content and attach sanitized correlation fields.

        Args:
            record: Log record shared by the JSON and OpenTelemetry handlers.

        Returns:
            Always ``True`` so the sanitized record is emitted.
        """
        record.msg = redact_telemetry_value(record.getMessage())
        record.args = ()
        for key, value in tuple(record.__dict__.items()):
            if key not in {"msg", "args", "exc_info", "exc_text"}:
                record.__dict__[key] = redact_telemetry_value(value, key=key)

        correlation = current_correlation_context()
        for field in _CORRELATION_FIELDS:
            candidate = getattr(record, field, "") or getattr(correlation, field)
            record.__dict__[field] = sanitize_identifier(str(candidate))
        record.__dict__["trace_id"] = current_trace_id()
        record.__dict__["span_id"] = current_span_id()

        if record.exc_info:
            record.__dict__["exception_type"] = getattr(
                record.exc_info[0], "__name__", "Exception"
            )
            stack = record.exc_text or logging.Formatter().formatException(
                record.exc_info
            )
            record.__dict__["exception_stack"] = _redact_string(stack)
            record.exc_info = None
            record.exc_text = None
        return True


class JsonLogFormatter(logging.Formatter):
    """Render only the approved operational log schema as compact JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize an already-filtered record to the allowlisted JSON schema.

        Args:
            record: Sanitized logging record.

        Returns:
            One compact JSON object without arbitrary record extras.
        """
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in (*_CORRELATION_FIELDS, "trace_id", "span_id"):
            value = getattr(record, field, "")
            if value:
                payload[field] = value
        if hasattr(record, "exception_type"):
            payload["exception_type"] = record.exception_type
            payload["exception_stack"] = getattr(record, "exception_stack", "")
        for field in _OPERATIONAL_EXTRAS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


__all__ = [
    "JsonLogFormatter",
    "TelemetryRedactionFilter",
    "redact_telemetry_value",
]
