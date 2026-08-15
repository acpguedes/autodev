"""Tests for typed OpenTelemetry configuration resolution."""

from __future__ import annotations

from typing import cast

import pytest
from opentelemetry.sdk.trace.sampling import (
    ParentBased,
    Sampler,
    StaticSampler,
    TraceIdRatioBased,
)
from pydantic import ValidationError

from backend.config.settings import OtelSamplerName, Settings
from backend.observability.configuration import (
    SignalName,
    build_sampler,
    resolve_signal_endpoint,
)


@pytest.mark.parametrize(
    ("name", "expected_type"),
    [
        ("always_on", StaticSampler),
        ("always_off", StaticSampler),
        ("traceidratio", TraceIdRatioBased),
        ("parentbased_always_on", ParentBased),
        ("parentbased_always_off", ParentBased),
        ("parentbased_traceidratio", ParentBased),
    ],
)
def test_build_sampler_supports_the_documented_vocabulary(
    name: OtelSamplerName, expected_type: type[Sampler]
) -> None:
    """Every configured sampler name resolves to the documented SDK sampler."""
    sampler = build_sampler(name, 0.25)
    assert isinstance(sampler, expected_type)


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        ("traces", "http://collector:4318/v1/traces"),
        ("metrics", "http://collector:4318/v1/metrics"),
        ("logs", "http://collector:4318/v1/logs"),
    ],
)
def test_base_otlp_endpoint_expands_per_signal(
    signal: SignalName, expected: str
) -> None:
    """A Collector base URL expands to the canonical path for each signal."""
    settings = Settings(otel_exporter_otlp_endpoint="http://collector:4318")
    assert resolve_signal_endpoint(settings, signal) == expected


def test_signal_specific_endpoint_wins() -> None:
    """A signal-specific endpoint overrides the shared Collector base URL."""
    settings = Settings(
        otel_exporter_otlp_endpoint="http://collector:4318",
        otel_exporter_otlp_metrics_endpoint="http://metrics:4318/custom",
    )
    assert resolve_signal_endpoint(settings, "metrics") == "http://metrics:4318/custom"


def test_endpoint_for_another_signal_is_not_reused() -> None:
    """A shared URL ending in one signal path cannot export another signal."""
    settings = Settings(otel_exporter_otlp_endpoint="http://collector:4318/v1/traces")
    assert (
        resolve_signal_endpoint(settings, "traces")
        == settings.otel_exporter_otlp_endpoint
    )
    assert resolve_signal_endpoint(settings, "metrics") == ""


def test_retention_and_sampling_are_validated() -> None:
    """Invalid retention syntax and undocumented sampler names are rejected."""
    with pytest.raises(ValidationError):
        Settings(autodev_observability_trace_retention="forever")
    with pytest.raises(ValidationError):
        Settings(otel_traces_sampler=cast(OtelSamplerName, "vendor_magic"))


def test_otlp_endpoints_are_redacted_from_feature_settings() -> None:
    """Credentials embedded in every OTLP endpoint stay out of settings dumps."""
    settings = Settings(
        otel_exporter_otlp_endpoint="https://user:secret@collector",
        otel_exporter_otlp_traces_endpoint="https://user:secret@traces",
        otel_exporter_otlp_metrics_endpoint="https://user:secret@metrics",
        otel_exporter_otlp_logs_endpoint="https://user:secret@logs",
    )

    redacted = settings.redacted_model_dump()

    assert redacted["otel_exporter_otlp_endpoint"] == "***"
    assert redacted["otel_exporter_otlp_traces_endpoint"] == "***"
    assert redacted["otel_exporter_otlp_metrics_endpoint"] == "***"
    assert redacted["otel_exporter_otlp_logs_endpoint"] == "***"
