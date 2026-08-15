"""Owned lifecycle for OpenTelemetry traces, metrics, and structured logs."""

from __future__ import annotations

import importlib.metadata
import logging
import sys
import threading
import uuid
import warnings
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from opentelemetry import _logs as logs
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogRecordExporter as LogExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider, TraceBasedExemplarFilter
from opentelemetry.sdk.metrics.export import (
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.util.types import Attributes

from backend.config.settings import Settings, get_settings
from backend.observability.configuration import build_sampler, resolve_signal_endpoint
from backend.observability.log_correlation import (
    JsonLogFormatter,
    TelemetryRedactionFilter,
)
from backend.observability.metrics import (
    MetricSink,
    NoopMetricSink,
    OtelMetricSink,
    set_metric_sink,
)

_ProviderT = TypeVar("_ProviderT")


class _ProviderDelegate(Generic[_ProviderT]):
    """Thread-safe mutable reference behind a process-lifetime provider facade."""

    def __init__(self, provider: _ProviderT) -> None:
        """Initialize the reference with a no-op provider.

        Args:
            provider: Initial delegate returned until a runtime is installed.
        """
        self._provider = provider
        self._lock = threading.RLock()

    def get(self) -> _ProviderT:
        """Return the provider currently serving global instrumentation.

        Returns:
            The current live or no-op provider.
        """
        with self._lock:
            return self._provider

    def set(self, provider: _ProviderT) -> None:
        """Switch global instrumentation to a new live provider.

        Args:
            provider: Newly active runtime provider.
        """
        with self._lock:
            self._provider = provider

    def clear(self, provider: _ProviderT, replacement: _ProviderT) -> None:
        """Replace an expected retiring provider with a no-op provider.

        Args:
            provider: Provider being retired by its runtime.
            replacement: No-op provider used until the next global runtime.
        """
        with self._lock:
            if self._provider is provider:
                self._provider = replacement


class _DelegatingTracerProvider(trace.TracerProvider):
    """Stable global tracer provider forwarding to the active runtime."""

    def __init__(self) -> None:
        """Initialize the facade with a public no-op tracer provider."""
        self._delegate = _ProviderDelegate[trace.TracerProvider](
            trace.NoOpTracerProvider()
        )

    def get_tracer(
        self,
        instrumenting_module_name: str,
        instrumenting_library_version: str | None = None,
        schema_url: str | None = None,
        attributes: Attributes = None,
    ) -> trace.Tracer:
        """Return a tracer from the active runtime provider.

        Args:
            instrumenting_module_name: Instrumentation scope name.
            instrumenting_library_version: Optional scope version.
            schema_url: Optional scope schema URL.
            attributes: Optional scope attributes.

        Returns:
            A tracer from the current live or no-op provider.
        """
        return self._delegate.get().get_tracer(
            instrumenting_module_name,
            instrumenting_library_version,
            schema_url,
            attributes,
        )


class _DelegatingMeterProvider(metrics.MeterProvider):
    """Stable global meter provider forwarding to the active runtime."""

    def __init__(self) -> None:
        """Initialize the facade with a public no-op meter provider."""
        self._delegate = _ProviderDelegate[metrics.MeterProvider](
            metrics.NoOpMeterProvider()
        )

    def get_meter(
        self,
        name: str,
        version: str | None = None,
        schema_url: str | None = None,
        attributes: Attributes = None,
    ) -> metrics.Meter:
        """Return a meter from the active runtime provider.

        Args:
            name: Instrumentation scope name.
            version: Optional scope version.
            schema_url: Optional scope schema URL.
            attributes: Optional scope attributes.

        Returns:
            A meter from the current live or no-op provider.
        """
        return self._delegate.get().get_meter(
            name,
            version,
            schema_url,
            attributes,
        )


class _DelegatingLoggerProvider(logs.LoggerProvider):
    """Stable global logger provider forwarding to the active runtime."""

    def __init__(self) -> None:
        """Initialize the facade with a public no-op logger provider."""
        self._delegate = _ProviderDelegate[logs.LoggerProvider](
            logs.NoOpLoggerProvider()
        )

    def get_logger(
        self,
        name: str,
        version: str | None = None,
        schema_url: str | None = None,
        attributes: Any = None,
    ) -> logs.Logger:
        """Return a logger from the active runtime provider.

        Args:
            name: Instrumentation scope name.
            version: Optional scope version.
            schema_url: Optional scope schema URL.
            attributes: Optional scope attributes.

        Returns:
            A logger from the current live or no-op provider.
        """
        return self._delegate.get().get_logger(
            name,
            version,
            schema_url,
            attributes,
        )


_runtime: ObservabilityRuntime | None = None
_global_facades_installed = False
_global_tracer_provider = _DelegatingTracerProvider()
_global_meter_provider = _DelegatingMeterProvider()
_global_logger_provider = _DelegatingLoggerProvider()


def _service_version() -> str:
    """Resolve the installed backend version without importing the API module.

    Returns:
        The installed package version, or the source-tree default.
    """
    try:
        return importlib.metadata.version("autodev-backend")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


@dataclass
class ObservabilityRuntime:
    """Own providers, handlers, metric sink, flushing, and orderly shutdown."""

    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    metric_sink: MetricSink
    log_handlers: tuple[logging.Handler, ...]
    _shutdown: bool = field(default=False, init=False, repr=False)
    _installed_global: bool = field(default=False, init=False, repr=False)

    def force_flush(self, timeout_millis: int = 10_000) -> bool:
        """Flush all three providers within their configured processor semantics.

        Args:
            timeout_millis: Maximum wait supplied independently to each provider.

        Returns:
            ``True`` only when every provider reports a successful flush.
        """
        if self._shutdown:
            return True
        results = (
            self.tracer_provider.force_flush(timeout_millis),
            self.meter_provider.force_flush(timeout_millis),
            self.logger_provider.force_flush(timeout_millis),
        )
        return all(results)

    def shutdown(self) -> None:
        """Remove owned handlers and shut down all providers once."""
        global _runtime
        if self._shutdown:
            return
        self._shutdown = True
        if self._installed_global:
            _clear_global_delegates(self)
        root_logger = logging.getLogger()
        for handler in self.log_handlers:
            root_logger.removeHandler(handler)
            handler.close()
        self.logger_provider.shutdown()
        self.meter_provider.shutdown()
        self.tracer_provider.shutdown()
        if _runtime is self:
            _runtime = None
            set_metric_sink(NoopMetricSink())


def _install_globals(runtime: ObservabilityRuntime) -> None:
    """Install stable global facades and point them at the active runtime.

    Args:
        runtime: Runtime whose providers should serve third-party instrumentation.
    """
    global _global_facades_installed
    _global_tracer_provider._delegate.set(runtime.tracer_provider)
    _global_meter_provider._delegate.set(runtime.meter_provider)
    _global_logger_provider._delegate.set(runtime.logger_provider)
    if not _global_facades_installed:
        trace.set_tracer_provider(_global_tracer_provider)
        metrics.set_meter_provider(_global_meter_provider)
        logs.set_logger_provider(_global_logger_provider)
        _global_facades_installed = True
    runtime._installed_global = True


def _clear_global_delegates(runtime: ObservabilityRuntime) -> None:
    """Detach a retiring runtime from the process-lifetime global facades.

    Args:
        runtime: Runtime whose providers are about to be shut down.
    """
    _global_tracer_provider._delegate.clear(
        runtime.tracer_provider, trace.NoOpTracerProvider()
    )
    _global_meter_provider._delegate.clear(
        runtime.meter_provider, metrics.NoOpMeterProvider()
    )
    _global_logger_provider._delegate.clear(
        runtime.logger_provider, logs.NoOpLoggerProvider()
    )
    runtime._installed_global = False


def _build_log_handlers(
    logger_provider: LoggerProvider,
    *,
    enabled: bool,
    log_exporter: LogExporter | None,
    endpoint: str,
) -> tuple[logging.Handler, ...]:
    """Build JSON and optional OTel handlers with one shared redaction filter.

    Args:
        logger_provider: Runtime-owned SDK logger provider.
        enabled: Whether OTel signal export is enabled.
        log_exporter: Optional injected synchronous test exporter.
        endpoint: Resolved production OTLP/HTTP log endpoint.

    Returns:
        Handlers installed on the root Python logger.
    """
    redaction_filter = TelemetryRedactionFilter()
    json_handler = logging.StreamHandler(sys.stdout)
    json_handler.setFormatter(JsonLogFormatter())
    json_handler.addFilter(redaction_filter)
    handlers: list[logging.Handler] = [json_handler]

    if enabled and log_exporter is not None:
        logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
    elif enabled and endpoint:
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint))
        )
    if enabled and (log_exporter is not None or endpoint):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"`LoggingHandler` in `opentelemetry-sdk` is deprecated.*",
                category=DeprecationWarning,
            )
            otel_handler = LoggingHandler(logger_provider=logger_provider)
        otel_handler.addFilter(redaction_filter)
        handlers.append(otel_handler)
    return tuple(handlers)


def configure_observability(
    settings: Settings | None = None,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
    log_exporter: LogExporter | None = None,
    service_name: str | None = None,
    install_global: bool = True,
) -> ObservabilityRuntime:
    """Configure one owned three-signal runtime.

    Injected exporters/readers use synchronous processors for deterministic
    tests. Production endpoints use OTLP/HTTP batch or periodic processors.

    Args:
        settings: Settings override; defaults to the cached application settings.
        span_exporter: Optional injected test span exporter.
        metric_reader: Optional injected test metric reader.
        log_exporter: Optional injected test log exporter.
        service_name: Optional resource service-name override.
        install_global: Whether to install providers in OTel global APIs.

    Returns:
        The newly configured process-owned runtime.
    """
    global _runtime
    if _runtime is not None:
        _runtime.shutdown()

    active = settings or get_settings()
    resource = Resource.create(
        {
            "service.name": service_name or active.otel_service_name,
            "service.version": _service_version(),
            "service.instance.id": str(uuid.uuid4()),
            "deployment.environment.name": active.autodev_profile,
        }
    )

    tracer_provider = TracerProvider(
        sampler=build_sampler(
            active.otel_traces_sampler, active.otel_traces_sampler_arg
        ),
        resource=resource,
        shutdown_on_exit=False,
    )
    trace_endpoint = resolve_signal_endpoint(active, "traces")
    if active.otel_enabled and span_exporter is not None:
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    elif active.otel_enabled and trace_endpoint:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=trace_endpoint))
        )

    readers: list[MetricReader] = []
    if active.otel_enabled and metric_reader is not None:
        readers.append(metric_reader)
    else:
        metric_endpoint = resolve_signal_endpoint(active, "metrics")
        if active.otel_enabled and metric_endpoint:
            readers.append(
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=metric_endpoint),
                    export_interval_millis=active.otel_metric_export_interval_ms,
                )
            )
    meter_provider = MeterProvider(
        metric_readers=readers,
        resource=resource,
        exemplar_filter=TraceBasedExemplarFilter(),
        shutdown_on_exit=False,
    )
    metric_sink: MetricSink
    if active.otel_enabled:
        metric_sink = OtelMetricSink(meter_provider.get_meter("backend.observability"))
    else:
        metric_sink = NoopMetricSink()

    logger_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
    handlers = _build_log_handlers(
        logger_provider,
        enabled=active.otel_enabled,
        log_exporter=log_exporter,
        endpoint=resolve_signal_endpoint(active, "logs"),
    )
    root_logger = logging.getLogger()
    for handler in handlers:
        root_logger.addHandler(handler)

    runtime = ObservabilityRuntime(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        metric_sink=metric_sink,
        log_handlers=handlers,
    )
    _runtime = runtime
    set_metric_sink(metric_sink)
    if install_global:
        _install_globals(runtime)
    return runtime


def get_observability_runtime() -> ObservabilityRuntime:
    """Return the active runtime, configuring local defaults on first access.

    Returns:
        The process-owned observability runtime.
    """
    if _runtime is None:
        return configure_observability()
    return _runtime


def get_tracer(scope: str = "backend.observability") -> trace.Tracer:
    """Return a tracer from the runtime-owned provider.

    Args:
        scope: Instrumentation scope name.

    Returns:
        An SDK tracer, or a non-recording tracer when OTel is disabled.
    """
    runtime = get_observability_runtime()
    if isinstance(runtime.metric_sink, NoopMetricSink):
        return trace.NoOpTracerProvider().get_tracer(scope)
    return runtime.tracer_provider.get_tracer(scope)


def get_meter(scope: str = "backend.observability") -> metrics.Meter:
    """Return a meter from the runtime-owned provider.

    Args:
        scope: Instrumentation scope name.

    Returns:
        A runtime-owned meter.
    """
    return get_observability_runtime().meter_provider.get_meter(scope)


def shutdown_observability() -> None:
    """Shut down the active runtime when one has been configured."""
    if _runtime is not None:
        _runtime.shutdown()


__all__ = [
    "ObservabilityRuntime",
    "configure_observability",
    "get_meter",
    "get_observability_runtime",
    "get_tracer",
    "shutdown_observability",
]
