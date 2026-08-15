"""OpenTelemetry setup and span helpers for AutoDev runs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace.export import (
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.config.settings import Settings, get_settings


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

    from backend.observability.runtime import configure_observability

    configure_observability(
        settings or get_settings(),
        span_exporter=span_exporter,
        service_name=service_name,
        install_global=span_exporter is None,
    )


def get_tracer() -> trace.Tracer:
    """Return the process tracer, configuring tracing on first use.

    Returns:
        The ``"backend.observability"`` tracer.
    """
    from backend.observability.runtime import get_tracer as runtime_get_tracer

    return runtime_get_tracer()


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


MODEL_ERROR_CODES = frozenset(
    {
        "provider_not_configured",
        "unsupported_capability",
        "authentication",
        "invalid_request",
        "rate_limit",
        "timeout",
        "unavailable",
        "budget_exceeded",
        "provider_error",
    }
)
"""Stable model error vocabulary allowed on spans.

Mirrors ``backend.llm.contracts.ModelErrorCode``. It is duplicated rather than
imported because ``backend.llm`` imports this module; a contract test asserts the
two stay identical.
"""


def _safe_error_code(code: str) -> str:
    """Clamp an error code to the stable vocabulary before it reaches a span.

    Provider SDK exceptions expose vendor codes such as ``invalid_api_key``.
    Recording those verbatim makes dashboards keyed on the stable vocabulary
    silently miss attempts, so anything unrecognized becomes ``provider_error``.

    Args:
        code: Candidate code, or an empty string when the attempt succeeded.

    Returns:
        A member of :data:`MODEL_ERROR_CODES`, or an empty string on success.
    """
    if not code:
        return ""
    return code if code in MODEL_ERROR_CODES else "provider_error"


@contextmanager
def _model_call_span(*, set_current: bool) -> Iterator[Any]:
    """Open the model span, optionally without making it the current span.

    Args:
        set_current: When ``False`` the span is not attached to the ambient
            context. Streaming callers need this: a generator suspends at each
            ``yield``, and an attached span would re-parent unrelated caller work
            onto the model call.

    Yields:
        The started span, ended when the block exits.
    """
    tracer = get_tracer()
    if set_current:
        # record_exception/set_status_on_exception are disabled deliberately.
        # OpenTelemetry would attach `str(exc)` verbatim, and provider
        # exceptions carry credentials: the caller-facing message is redacted
        # downstream, but the span event would already hold the raw key. This
        # span reports a stable error code and never an exception message.
        with tracer.start_as_current_span(
            "autodev.model.call",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            yield span
        return
    span = tracer.start_span("autodev.model.call")
    try:
        yield span
    finally:
        span.end()


@contextmanager
def trace_model_call(
    *,
    agent_id: str,
    provider: str,
    model: str,
    fallback_attempt: int,
    set_current: bool = True,
) -> Iterator[ModelCallTrace]:
    """Trace one provider attempt without recording prompt or secret content.

    Args:
        agent_id: Agent issuing the call.
        provider: Registered provider id.
        model: Provider model id.
        fallback_attempt: Zero-based target index in the fallback chain.
        set_current: Whether the span becomes the current span. Streaming
            callers pass ``False`` so suspended generators do not capture
            unrelated caller spans as children.

    Yields:
        Mutable measurement fields finalized as safe span attributes.
    """
    measurements = ModelCallTrace()
    with _model_call_span(set_current=set_current) as span:
        try:
            yield measurements
        except GeneratorExit:
            # The consumer stopped iterating a streamed attempt. That is not a
            # provider failure -- most often it is `break` after the terminal
            # chunk -- so the span must not be marked ERROR.
            raise
        except BaseException as exc:
            if not measurements.error_code:
                # An exception without its own code is still a failure; falling
                # back to an empty code would render it as a successful span.
                measurements.error_code = (
                    str(getattr(exc, "code", "") or "") or "provider_error"
                )
            raise
        finally:
            # Sanitizing here rather than at each assignment makes this the one
            # place a code can reach a span, whatever a caller wrote onto the
            # mutable measurements.
            error_code = _safe_error_code(measurements.error_code)
            span.set_attributes(
                model_call_span_attributes(
                    agent_id=agent_id,
                    provider=provider,
                    model=model,
                    latency_ms=measurements.latency_ms,
                    input_tokens=measurements.input_tokens,
                    output_tokens=measurements.output_tokens,
                    estimated_cost_usd=measurements.estimated_cost_usd,
                    error_code=error_code,
                    fallback_attempt=fallback_attempt,
                )
            )
            if error_code:
                # Status description is the stable code, never the provider
                # message, which may contain credentials.
                span.set_status(Status(StatusCode.ERROR, error_code))


__all__ = [
    "MODEL_ERROR_CODES",
    "InMemorySpanExporter",
    "configure_tracing",
    "get_tracer",
    "model_call_span_attributes",
    "step_span_attributes",
    "trace_model_call",
    "trace_run_step",
]
