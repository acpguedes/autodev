"""Tests for structured logging, correlation, and shared redaction."""

from __future__ import annotations

import io
import logging

from backend.observability.context import bind_correlation_context
from backend.observability.log_correlation import TelemetryRedactionFilter
from backend.observability.tracing import get_tracer
from backend.tests.observability_helpers import capture_observability


def test_json_and_otlp_logs_share_redaction_and_correlation() -> None:
    """Both log paths redact the same record and include active correlation ids."""
    stream = io.StringIO()
    with capture_observability(log_stream=stream) as capture:
        with bind_correlation_context(run_id="run-1", tenant_id="tenant-1"):
            with get_tracer().start_as_current_span("log-test"):
                logging.getLogger("backend.test").info(
                    "Authorization: Bearer secret-value user@example.com",
                    extra={"step_id": "step-1"},
                )
        capture.runtime.force_flush()

    rendered = stream.getvalue()
    assert '"run_id":"run-1"' in rendered
    assert '"tenant_id":"tenant-1"' in rendered
    assert '"trace_id":"' in rendered
    assert "secret-value" not in rendered
    assert "user@example.com" not in rendered
    assert all(
        "secret-value" not in str(record.log_record.body)
        for record in capture.log_exporter.get_finished_logs()
    )


def test_redaction_recurses_through_sensitive_keys_and_sequences() -> None:
    """Structured extras cannot bypass redaction through nested containers."""
    record = logging.LogRecord(
        name="backend.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="api_key=sk-live bare sk-abcdefghijk email user@example.com",
        args=(),
        exc_info=None,
    )
    record.event = {
        "authorization_header": "Bearer hidden",
        "safe": ["plain", {"password": "also-hidden"}],
    }

    assert TelemetryRedactionFilter().filter(record)

    assert "sk-live" not in record.getMessage()
    assert "sk-abcdefghijk" not in record.getMessage()
    assert "user@example.com" not in record.getMessage()
    event = getattr(record, "event")
    assert event["authorization_header"] == "[REDACTED]"
    assert event["safe"][1]["password"] == "[REDACTED]"


def test_json_formatter_omits_unallowlisted_extras() -> None:
    """Structured JSON includes operational extras but drops arbitrary payloads."""
    stream = io.StringIO()
    with capture_observability(log_stream=stream):
        logging.getLogger("backend.test").info(
            "operation finished",
            extra={"event": "run.finished", "payload": "private-body"},
        )

    rendered = stream.getvalue()
    assert '"event":"run.finished"' in rendered
    assert "private-body" not in rendered


def test_exception_messages_and_stacks_are_redacted_before_otlp_export() -> None:
    """Raw exception content cannot leak through OTel exception attributes."""
    stream = io.StringIO()
    with capture_observability(log_stream=stream) as capture:
        try:
            raise RuntimeError("Bearer exception-secret user@example.com")
        except RuntimeError:
            logging.getLogger("backend.test").exception("operation failed")
        capture.runtime.force_flush()

    rendered = stream.getvalue()
    exported = " ".join(
        f"{record.log_record.body!r} {record.log_record.attributes!r}"
        for record in capture.log_exporter.get_finished_logs()
    )
    assert "exception-secret" not in rendered
    assert "user@example.com" not in rendered
    assert "exception-secret" not in exported
    assert "user@example.com" not in exported
    assert '"exception_type":"RuntimeError"' in rendered
    assert '"exception_stack":"' in rendered
