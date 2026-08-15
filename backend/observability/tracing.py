"""OpenTelemetry setup and span helpers for AutoDev runs."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any, Iterator, Literal

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace.export import (
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.util.types import AttributeValue

from backend.config.settings import Settings, get_settings
from backend.observability.context import (
    bind_correlation_context,
    current_correlation_context,
    sanitize_identifier,
)
from backend.observability.metrics import get_metric_sink

logger = logging.getLogger(__name__)

_DECISION_ATTRIBUTES = {
    "strategy_id": "autodev.decision.strategy_id",
    "selection_source": "autodev.decision.selection_source",
    "task_type": "autodev.decision.task_type",
    "intent": "autodev.decision.intent",
    "agent_id": "autodev.decision.agent_id",
    "model_id": "autodev.decision.model_id",
    "gate_result": "autodev.decision.gate_result",
}
_OPERATION_ERROR_CODES = frozenset(
    {
        "binding_error",
        "budget_exhausted",
        "command_blocked",
        "dependency_failed",
        "guardrail_blocked",
        "handler_failed",
        "invalid_output",
        "no_route",
        "node_failed",
        "predicate_error",
        "sandbox_unavailable",
        "unhandled_error",
        "unsupported_node",
        "validation_failed",
    }
)


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


@dataclass
class RunTrace:
    """Mutable bounded measurements finalized before a run span closes."""

    status: str = "running"
    error_code: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def finish(
        self,
        *,
        status: str,
        error_code: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Set the final safe run outcome and aggregate measurements.

        Args:
            status: Stable terminal run status.
            error_code: Stable machine-readable error code.
            input_tokens: Total input tokens consumed.
            output_tokens: Total output tokens consumed.
            cost_usd: Estimated total cost in US dollars.
        """
        self.status = status
        self.error_code = error_code
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd


@dataclass
class StepTrace:
    """Mutable bounded outcome finalized before a step span closes."""

    status: str = "running"
    error_code: str = ""

    def finish(self, *, status: str, error_code: str = "") -> None:
        """Set the final safe step outcome.

        Args:
            status: Stable final step or dependency status.
            error_code: Stable machine-readable error code.
        """
        self.status = status
        self.error_code = error_code


def _safe_operation_error_code(code: str) -> str:
    """Clamp run, step, and dependency failures to stable safe codes.

    Args:
        code: Candidate machine-readable error code.

    Returns:
        A known operation error code, an empty string, or ``unhandled_error``.
    """
    if not code:
        return ""
    return code if code in _OPERATION_ERROR_CODES else "unhandled_error"


@contextmanager
def trace_run(*, run_id: str, tenant_id: str, flow_id: str) -> Iterator[RunTrace]:
    """Trace one run and finalize its span, metric, and completion log.

    Args:
        run_id: Domain run identifier.
        tenant_id: Tenant that owns the run.
        flow_id: Flow or orchestration identifier.

    Yields:
        Mutable safe measurements for the final run outcome.
    """
    parent = current_correlation_context()
    safe_run_id = sanitize_identifier(run_id or parent.run_id)
    safe_tenant_id = sanitize_identifier(tenant_id or parent.tenant_id)
    safe_flow_id = sanitize_identifier(flow_id)
    measurements = RunTrace()
    started = time.perf_counter()
    with bind_correlation_context(run_id=safe_run_id, tenant_id=safe_tenant_id):
        with get_tracer().start_as_current_span(
            "autodev.run",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield measurements
            except BaseException:
                if not measurements.error_code:
                    measurements.finish(status="failed", error_code="unhandled_error")
                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        _safe_operation_error_code(measurements.error_code),
                    )
                )
                raise
            finally:
                elapsed = time.perf_counter() - started
                status = sanitize_identifier(measurements.status)
                error_code = _safe_operation_error_code(measurements.error_code)
                span.set_attributes(
                    {
                        "autodev.run_id": safe_run_id,
                        "autodev.tenant_id": safe_tenant_id,
                        "autodev.flow_id": safe_flow_id,
                        "autodev.status": status,
                        "autodev.error_code": error_code,
                        "autodev.tokens.input": measurements.input_tokens,
                        "autodev.tokens.output": measurements.output_tokens,
                        "autodev.cost_usd": measurements.cost_usd,
                    }
                )
                if error_code:
                    span.set_status(Status(StatusCode.ERROR, error_code))
                get_metric_sink().record_run(
                    tenant_id=safe_tenant_id,
                    flow_id=safe_flow_id,
                    status=status,
                    duration_seconds=elapsed,
                    input_tokens=measurements.input_tokens,
                    output_tokens=measurements.output_tokens,
                    cost_usd=measurements.cost_usd,
                )
                logger.info(
                    "run completed",
                    extra={
                        "event": "run.completed",
                        "status": status,
                        "duration_s": round(elapsed, 6),
                        "error_code": error_code,
                    },
                )


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
    status: str = "running",
    tenant_id: str = "",
) -> Iterator[StepTrace]:
    """Trace a single agent run step as an OpenTelemetry span.

    Args:
        run_id: Identifier of the run.
        step_id: Identifier of the step.
        agent: Identifier of the agent executing the step.
        status: Step outcome status.
        tenant_id: Tenant that owns the run.

    Yields:
        Mutable safe outcome finalized before the span closes.
    """
    safe_run_id = sanitize_identifier(run_id)
    safe_step_id = sanitize_identifier(step_id)
    safe_agent = sanitize_identifier(agent)
    safe_tenant_id = sanitize_identifier(
        tenant_id or current_correlation_context().tenant_id
    )
    measurements = StepTrace(status=status)
    started = time.perf_counter()
    attrs = step_span_attributes(
        run_id=safe_run_id,
        step_id=safe_step_id,
        agent=safe_agent,
        status=status,
    )
    attrs["autodev.tenant_id"] = safe_tenant_id
    with bind_correlation_context(
        run_id=safe_run_id,
        step_id=safe_step_id,
        tenant_id=safe_tenant_id,
    ):
        with get_tracer().start_as_current_span(
            f"autodev.run.step.{safe_step_id}",
            attributes=attrs,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield measurements
            except BaseException:
                if not measurements.error_code:
                    measurements.finish(status="failed", error_code="unhandled_error")
                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        _safe_operation_error_code(measurements.error_code),
                    )
                )
                raise
            finally:
                elapsed = time.perf_counter() - started
                final_status = sanitize_identifier(measurements.status)
                error_code = _safe_operation_error_code(measurements.error_code)
                span.set_attributes(
                    {
                        "autodev.status": final_status,
                        "autodev.error_code": error_code,
                    }
                )
                if error_code:
                    span.set_status(Status(StatusCode.ERROR, error_code))
                get_metric_sink().record_step(
                    tenant_id=safe_tenant_id,
                    agent_id=safe_agent,
                    status=final_status,
                    duration_seconds=elapsed,
                )
                logger.info(
                    "run step completed",
                    extra={
                        "event": "run.step.completed",
                        "status": final_status,
                        "duration_s": round(elapsed, 6),
                        "error_code": error_code,
                    },
                )


@contextmanager
def trace_dependency(
    *,
    kind: Literal["tool", "skill", "sandbox"],
    name: str,
    run_id: str = "",
    tenant_id: str = "",
) -> Iterator[StepTrace]:
    """Trace one bounded tool, skill, or sandbox dependency operation.

    Args:
        kind: Stable dependency category.
        name: Granted dependency identifier.
        run_id: Correlated run identifier, when available.
        tenant_id: Correlated tenant identifier, when available.

    Yields:
        Mutable safe dependency outcome.
    """
    safe_name = sanitize_identifier(name)
    parent = current_correlation_context()
    safe_run_id = sanitize_identifier(run_id or parent.run_id)
    safe_tenant_id = sanitize_identifier(tenant_id or parent.tenant_id)
    measurements = StepTrace()
    with bind_correlation_context(run_id=safe_run_id, tenant_id=safe_tenant_id):
        with get_tracer().start_as_current_span(
            f"autodev.dependency.{kind}",
            attributes={
                "autodev.dependency.kind": kind,
                "autodev.dependency.name": safe_name,
                "autodev.run_id": safe_run_id,
                "autodev.tenant_id": safe_tenant_id,
            },
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield measurements
            except BaseException:
                if not measurements.error_code:
                    measurements.finish(status="failed", error_code="unhandled_error")
                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        _safe_operation_error_code(measurements.error_code),
                    )
                )
                raise
            finally:
                final_status = sanitize_identifier(measurements.status)
                error_code = _safe_operation_error_code(measurements.error_code)
                span.set_attributes(
                    {
                        "autodev.status": final_status,
                        "autodev.error_code": error_code,
                    }
                )
                if error_code:
                    span.set_status(Status(StatusCode.ERROR, error_code))


def record_decision(
    *,
    name: str,
    outcome: str,
    tenant_id: str = "",
    run_id: str = "",
    attributes: Mapping[str, AttributeValue] | None = None,
) -> None:
    """Record one content-free operational decision span and metric.

    Args:
        name: Stable decision category.
        outcome: Stable decision outcome.
        tenant_id: Tenant identifier, when available.
        run_id: Run identifier, when available.
        attributes: Optional bounded decision dimensions. Unknown keys and
            mapping values are ignored.
    """
    safe_name = sanitize_identifier(name)
    safe_outcome = sanitize_identifier(outcome)
    parent = current_correlation_context()
    safe_tenant_id = sanitize_identifier(tenant_id or parent.tenant_id)
    safe_run_id = sanitize_identifier(run_id or parent.run_id)
    safe_attributes: dict[str, AttributeValue] = {
        "autodev.decision.type": safe_name,
        "autodev.decision.outcome": safe_outcome,
        "autodev.tenant_id": safe_tenant_id,
        "autodev.run_id": safe_run_id,
    }
    for key, value in (attributes or {}).items():
        target = _DECISION_ATTRIBUTES.get(key)
        if target is None or isinstance(value, Mapping):
            continue
        if isinstance(value, str):
            safe_attributes[target] = sanitize_identifier(value)
        elif isinstance(value, (bool, int, float)):
            safe_attributes[target] = value
    with bind_correlation_context(run_id=safe_run_id, tenant_id=safe_tenant_id):
        with get_tracer().start_as_current_span(
            f"autodev.decision.{safe_name}",
            attributes=safe_attributes,
            record_exception=False,
            set_status_on_exception=False,
        ):
            get_metric_sink().record_decision(
                tenant_id=safe_tenant_id,
                decision_type=safe_name,
                outcome=safe_outcome,
            )


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
    run_id: str = "",
    tenant_id: str = "",
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
        run_id: Correlated run identifier, when available.
        tenant_id: Correlated tenant identifier, when available.

    Returns:
        Flat OpenTelemetry-compatible attributes without request content.
    """
    attributes: dict[str, str | int | float] = {
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
    if run_id:
        attributes["autodev.run_id"] = sanitize_identifier(run_id)
    if tenant_id:
        attributes["autodev.tenant_id"] = sanitize_identifier(tenant_id)
    return attributes


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
    run_id: str = "",
    tenant_id: str = "",
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
        run_id: Correlated run identifier, when available.
        tenant_id: Correlated tenant identifier, when available.

    Yields:
        Mutable measurement fields finalized as safe span attributes.
    """
    measurements = ModelCallTrace()
    parent = current_correlation_context()
    safe_run_id = sanitize_identifier(run_id or parent.run_id)
    safe_tenant_id = sanitize_identifier(tenant_id or parent.tenant_id)
    binding = (
        bind_correlation_context(run_id=safe_run_id, tenant_id=safe_tenant_id)
        if set_current
        else nullcontext()
    )
    with binding:
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
                        run_id=safe_run_id,
                        tenant_id=safe_tenant_id,
                    )
                )
                if error_code:
                    # Status description is the stable code, never the provider
                    # message, which may contain credentials.
                    span.set_status(Status(StatusCode.ERROR, error_code))
                get_metric_sink().record_model_call(
                    tenant_id=safe_tenant_id,
                    agent_id=agent_id,
                    provider=provider,
                    model=model,
                    error_code=error_code,
                    duration_seconds=measurements.latency_ms / 1000.0,
                    input_tokens=measurements.input_tokens,
                    output_tokens=measurements.output_tokens,
                    cost_usd=measurements.estimated_cost_usd,
                )


__all__ = [
    "MODEL_ERROR_CODES",
    "InMemorySpanExporter",
    "RunTrace",
    "StepTrace",
    "configure_tracing",
    "get_tracer",
    "model_call_span_attributes",
    "record_decision",
    "step_span_attributes",
    "trace_model_call",
    "trace_dependency",
    "trace_run",
    "trace_run_step",
]
