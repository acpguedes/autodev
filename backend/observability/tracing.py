"""OpenTelemetry setup and span helpers for AutoDev runs."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.config.settings import Settings, get_settings

_configured = False
_provider: TracerProvider | None = None


def configure_tracing(
    settings: Settings | None = None,
    *,
    span_exporter: SpanExporter | None = None,
    service_name: str | None = None,
) -> None:
    """Configure OpenTelemetry tracing once for the process.

    Tests can pass ``span_exporter`` to force an in-memory exporter before app
    startup configures the default provider.

    Args:
        settings: Settings override; falls back to :func:`get_settings`.
        span_exporter: Exporter to attach directly, bypassing OTLP configuration.
        service_name: Service name to record on the tracer's resource; falls
            back to ``settings.otel_service_name``.
    """

    global _configured, _provider
    if _provider is not None and span_exporter is not None:
        _provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        return
    if _configured:
        return

    active = settings or get_settings()
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": service_name or active.otel_service_name}
        )
    )
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    elif active.otel_exporter_otlp_endpoint.strip():
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=active.otel_exporter_otlp_endpoint)
            )
        )
    trace.set_tracer_provider(provider)
    _provider = provider
    _configured = True


def get_tracer() -> trace.Tracer:
    """Return the process tracer, configuring tracing on first use.

    Returns:
        The ``"backend.observability"`` tracer.
    """
    configure_tracing()
    return trace.get_tracer("backend.observability")


def step_span_attributes(
    *,
    run_id: str,
    step_id: str,
    agent: str,
    status: str,
) -> dict[str, str]:
    """Return non-PII span attributes for a run step.

    Args:
        run_id: Identifier of the run.
        step_id: Identifier of the step.
        agent: Identifier of the agent executing the step.
        status: Step outcome status.

    Returns:
        The span attributes as a flat string-keyed dict.
    """

    return {
        "autodev.run_id": run_id,
        "autodev.step_id": step_id,
        "autodev.agent": agent,
        "autodev.status": status,
    }


@contextmanager
def trace_run_step(
    *,
    run_id: str,
    step_id: str,
    agent: str,
    status: str,
) -> Iterator[None]:
    """Trace a single agent run step as an OpenTelemetry span.

    Args:
        run_id: Identifier of the run.
        step_id: Identifier of the step.
        agent: Identifier of the agent executing the step.
        status: Step outcome status.

    Yields:
        Control to the traced block.
    """
    attrs = step_span_attributes(
        run_id=run_id,
        step_id=step_id,
        agent=agent,
        status=status,
    )
    with get_tracer().start_as_current_span(
        f"autodev.run.step.{step_id}",
        attributes=attrs,
    ):
        yield


__all__ = [
    "InMemorySpanExporter",
    "configure_tracing",
    "get_tracer",
    "step_span_attributes",
    "trace_run_step",
]
