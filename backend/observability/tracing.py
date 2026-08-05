"""OpenTelemetry setup and span helpers for AutoDev runs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
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


def model_call_span_attributes(
    *,
    agent_id: str,
    provider: str,
    model: str,
    latency_ms: float,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float,
    error_code: str,
    fallback_attempt: int,
) -> dict[str, str | int | float]:
    """Return prompt-free and credential-free model span attributes.

    Args:
        agent_id: Agent issuing the model call.
        provider: Registered provider id.
        model: Provider model id.
        latency_ms: Attempt latency in milliseconds.
        input_tokens: Normalized input-token count.
        output_tokens: Normalized output-token count.
        estimated_cost_usd: Estimated attempt cost in US dollars.
        error_code: Stable gateway error code or an empty string.
        fallback_attempt: Zero-based target index in the fallback chain.

    Returns:
        Flat OpenTelemetry-compatible attributes without request content.
    """
    return {
        "autodev.model.agent_id": agent_id,
        "autodev.model.provider": provider,
        "autodev.model.name": model,
        "autodev.model.latency_ms": latency_ms,
        "autodev.model.tokens.input": input_tokens,
        "autodev.model.tokens.output": output_tokens,
        "autodev.model.estimated_cost_usd": estimated_cost_usd,
        "autodev.model.error_code": error_code,
        "autodev.model.fallback_attempt": fallback_attempt,
    }


@dataclass
class ModelCallTrace:
    """Mutable safe measurements finalized when a model span closes."""

    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    error_code: str = ""


@contextmanager
def trace_model_call(
    *,
    agent_id: str,
    provider: str,
    model: str,
    fallback_attempt: int,
) -> Iterator[ModelCallTrace]:
    """Trace one provider attempt without recording prompt or secret content.

    Args:
        agent_id: Agent issuing the call.
        provider: Registered provider id.
        model: Provider model id.
        fallback_attempt: Zero-based target index in the fallback chain.

    Yields:
        Mutable measurement fields finalized as safe span attributes.
    """
    measurements = ModelCallTrace()
    with get_tracer().start_as_current_span("autodev.model.call") as span:
        try:
            yield measurements
        except BaseException as exc:
            measurements.error_code = str(getattr(exc, "code", "provider_error"))
            raise
        finally:
            span.set_attributes(
                model_call_span_attributes(
                    agent_id=agent_id,
                    provider=provider,
                    model=model,
                    latency_ms=measurements.latency_ms,
                    input_tokens=measurements.input_tokens,
                    output_tokens=measurements.output_tokens,
                    estimated_cost_usd=measurements.estimated_cost_usd,
                    error_code=measurements.error_code,
                    fallback_attempt=fallback_attempt,
                )
            )


__all__ = [
    "InMemorySpanExporter",
    "configure_tracing",
    "get_tracer",
    "model_call_span_attributes",
    "step_span_attributes",
    "trace_model_call",
    "trace_run_step",
]
