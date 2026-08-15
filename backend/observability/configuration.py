"""Typed OpenTelemetry endpoint and sampling configuration."""

from __future__ import annotations

from typing import Literal

from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    Sampler,
    TraceIdRatioBased,
)

from backend.config.settings import OtelSamplerName, Settings

SignalName = Literal["traces", "metrics", "logs"]

_SIGNAL_PATHS: dict[SignalName, str] = {
    "traces": "/v1/traces",
    "metrics": "/v1/metrics",
    "logs": "/v1/logs",
}


def resolve_signal_endpoint(settings: Settings, signal: SignalName) -> str:
    """Resolve the configured OTLP/HTTP endpoint for one signal.

    Args:
        settings: Application settings containing shared and signal endpoints.
        signal: Signal whose exporter endpoint is required.

    Returns:
        The signal-specific URL, the expanded Collector URL, or an empty string
        when export for the signal is not configured.
    """
    specific = getattr(settings, f"otel_exporter_otlp_{signal}_endpoint").strip()
    if specific:
        return specific
    base = settings.otel_exporter_otlp_endpoint.strip().rstrip("/")
    if not base:
        return ""
    if base.endswith(tuple(_SIGNAL_PATHS.values())):
        return base if base.endswith(_SIGNAL_PATHS[signal]) else ""
    return f"{base}{_SIGNAL_PATHS[signal]}"


def build_sampler(name: OtelSamplerName, ratio: float) -> Sampler:
    """Build an SDK sampler from the documented configuration vocabulary.

    Args:
        name: Validated sampler name.
        ratio: Trace-id ratio used by ratio-based root samplers.

    Returns:
        The corresponding OpenTelemetry sampler.
    """
    roots: dict[str, Sampler] = {
        "always_on": ALWAYS_ON,
        "always_off": ALWAYS_OFF,
        "traceidratio": TraceIdRatioBased(ratio),
    }
    if name in roots:
        return roots[name]
    parent_roots = {
        "parentbased_always_on": ALWAYS_ON,
        "parentbased_always_off": ALWAYS_OFF,
        "parentbased_traceidratio": TraceIdRatioBased(ratio),
    }
    return ParentBased(parent_roots[name])


__all__ = ["SignalName", "build_sampler", "resolve_signal_endpoint"]
