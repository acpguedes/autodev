"""Test helpers for isolated three-signal observability runtimes."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO

from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from backend.config.settings import Settings
from backend.observability.runtime import ObservabilityRuntime, configure_observability


@dataclass(frozen=True)
class ObservabilityCapture:
    """Hold one isolated runtime and its in-memory signal readers/exporters."""

    runtime: ObservabilityRuntime
    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader
    log_exporter: InMemoryLogRecordExporter


@contextmanager
def capture_observability(
    *, log_stream: StringIO | None = None
) -> Iterator[ObservabilityCapture]:
    """Configure and clean up an isolated observability runtime.

    Args:
        log_stream: Optional text stream receiving structured JSON logs.

    Yields:
        The runtime together with its in-memory signal collectors.
    """
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    log_exporter = InMemoryLogRecordExporter()
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    target_stream = log_stream or StringIO()
    previous_stdout = sys.stdout
    sys.stdout = target_stream
    try:
        runtime = configure_observability(
            Settings(),
            span_exporter=span_exporter,
            metric_reader=metric_reader,
            log_exporter=log_exporter,
            install_global=False,
        )
    finally:
        sys.stdout = previous_stdout
    try:
        yield ObservabilityCapture(
            runtime=runtime,
            span_exporter=span_exporter,
            metric_reader=metric_reader,
            log_exporter=log_exporter,
        )
    finally:
        runtime.shutdown()
        root_logger.setLevel(previous_level)
