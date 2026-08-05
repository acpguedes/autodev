"""Tests for safe model-call OpenTelemetry attributes."""

from __future__ import annotations

from backend.observability.tracing import model_call_span_attributes


def test_model_call_attributes_include_governance_fields_and_exclude_content() -> None:
    """Model spans expose operational dimensions without prompts or credentials."""
    attributes = model_call_span_attributes(
        agent_id="acme/coder",
        provider="openai",
        model="gpt-test",
        latency_ms=12.5,
        input_tokens=4,
        output_tokens=2,
        estimated_cost_usd=0.01,
        error_code="timeout",
        fallback_attempt=2,
    )

    assert attributes == {
        "autodev.model.agent_id": "acme/coder",
        "autodev.model.provider": "openai",
        "autodev.model.name": "gpt-test",
        "autodev.model.latency_ms": 12.5,
        "autodev.model.tokens.input": 4,
        "autodev.model.tokens.output": 2,
        "autodev.model.estimated_cost_usd": 0.01,
        "autodev.model.error_code": "timeout",
        "autodev.model.fallback_attempt": 2,
    }
    assert all("prompt" not in key and "secret" not in key for key in attributes)
