"""Stable observability interfaces for traces, metrics, and structured logs."""

from backend.observability.context import (
    CorrelationContext,
    attach_execution_context,
    bind_correlation_context,
    capture_execution_context,
    current_correlation_context,
    current_span_id,
    current_trace_id,
    sanitize_identifier,
)
from backend.observability.middleware import (
    MetricsRegistry,
    RequestTracingMiddleware,
    attach,
    get_registry,
)
from backend.observability.metrics import (
    MetricSink,
    NoopMetricSink,
    OtelMetricSink,
    QueueSnapshot,
    get_metric_sink,
    set_metric_sink,
)
from backend.observability.runtime import (
    ObservabilityRuntime,
    configure_observability,
    get_meter,
    get_observability_runtime,
    get_tracer,
    shutdown_observability,
)

__all__ = [
    "CorrelationContext",
    "MetricsRegistry",
    "MetricSink",
    "NoopMetricSink",
    "ObservabilityRuntime",
    "OtelMetricSink",
    "QueueSnapshot",
    "RequestTracingMiddleware",
    "attach",
    "attach_execution_context",
    "bind_correlation_context",
    "capture_execution_context",
    "configure_observability",
    "current_correlation_context",
    "current_span_id",
    "current_trace_id",
    "get_meter",
    "get_metric_sink",
    "get_observability_runtime",
    "get_registry",
    "get_tracer",
    "sanitize_identifier",
    "set_metric_sink",
    "shutdown_observability",
]
