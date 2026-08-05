"""Tests for provider-neutral model configuration parsing."""

from __future__ import annotations

import math

import pytest

from backend.llm.model_config import ModelConfigError, parse_model_config


def _valid_model_config() -> dict[str, object]:
    """Return the canonical E2-S6 model configuration example."""
    return {
        "provider": "stub",
        "name": "coder-primary",
        "temperature": 0.1,
        "maxTokens": 8000,
        "timeoutSeconds": 30,
        "retries": 1,
        "requiredCapabilities": ["text"],
        "fallbackOn": ["timeout", "rate_limit", "unavailable"],
        "limits": {
            "maxCalls": 4,
            "maxTotalTokens": 16000,
            "maxCostUsd": 1.0,
        },
        "fallback": [
            {
                "provider": "stub",
                "name": "coder-safe",
            }
        ],
    }


def test_parse_model_config_accepts_canonical_camel_case_syntax() -> None:
    """The canonical manifest syntax parses into immutable typed configuration."""
    config = parse_model_config(_valid_model_config())

    assert config.provider == "stub"
    assert config.name == "coder-primary"
    assert config.max_tokens == 8000
    assert config.timeout_seconds == 30.0
    assert config.required_capabilities == ("text",)
    assert config.fallback_on == ("timeout", "rate_limit", "unavailable")
    assert config.limits.max_calls == 4
    assert config.limits.max_total_tokens == 16000
    assert config.limits.max_cost_usd == 1.0
    assert config.fallback[0].name == "coder-safe"
    assert config.fallback[0].temperature is None


def test_parse_model_config_accepts_complete_capability_and_error_vocabularies() -> (
    None
):
    """Every governed capability and normalized error id is accepted by the parser."""
    raw = _valid_model_config()
    raw["requiredCapabilities"] = [
        "text",
        "tool_calling",
        "structured_output",
        "streaming",
    ]
    raw["fallbackOn"] = [
        "provider_not_configured",
        "unsupported_capability",
        "authentication",
        "invalid_request",
        "timeout",
        "rate_limit",
        "unavailable",
        "budget_exceeded",
        "provider_error",
    ]

    config = parse_model_config(raw)

    assert config.required_capabilities == (
        "text",
        "tool_calling",
        "structured_output",
        "streaming",
    )
    assert config.fallback_on == (
        "provider_not_configured",
        "unsupported_capability",
        "authentication",
        "invalid_request",
        "timeout",
        "rate_limit",
        "unavailable",
        "budget_exceeded",
        "provider_error",
    )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("provider",), " ", "model.provider must be a non-blank string"),
        (("name",), "", "model.name must be a non-blank string"),
        (("temperature",), 2.1, "model.temperature must be between 0 and 2"),
        (("maxTokens",), 0, "model.maxTokens must be a positive integer"),
        (("timeoutSeconds",), -1, "model.timeoutSeconds must be a positive number"),
        (("retries",), 6, "model.retries must be an integer between 0 and 5"),
        (
            ("requiredCapabilities",),
            ["telepathy"],
            "unknown model capability telepathy",
        ),
        (("fallbackOn",), ["overloaded"], "unknown model error overloaded"),
        (("limits", "maxCalls"), 0, "model.limits.maxCalls must be a positive integer"),
        (
            ("limits", "maxCostUsd"),
            0.0,
            "model.limits.maxCostUsd must be a positive number",
        ),
        (
            ("limits", "maxCostUsd"),
            math.nan,
            "model.limits.maxCostUsd must be a positive number",
        ),
        (
            ("timeoutSeconds",),
            math.inf,
            "model.timeoutSeconds must be a positive number",
        ),
    ],
)
def test_parse_model_config_rejects_invalid_values(
    path: tuple[str, ...], value: object, message: str
) -> None:
    """Every governed numeric and vocabulary field fails closed on invalid input."""
    raw = _valid_model_config()
    target: dict[str, object] = raw
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    with pytest.raises(ModelConfigError, match=message):
        parse_model_config(raw)


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "apiKey",
        "secretKey",
        "accessKey",
        "secretAccessKey",
        "awsAccessKeyId",
        "refreshToken",
        "databasePassword",
        "serviceCredentials",
    ],
)
def test_parse_model_config_rejects_sensitive_keys_recursively(
    sensitive_key: str,
) -> None:
    """Credentials cannot be smuggled into nested model or fallback configuration."""
    raw = _valid_model_config()
    fallback = raw["fallback"]
    assert isinstance(fallback, list)
    assert isinstance(fallback[0], dict)
    fallback[0]["metadata"] = {sensitive_key: "must-not-live-in-manifest"}

    with pytest.raises(ModelConfigError) as exc_info:
        parse_model_config(raw)

    assert (
        f"model.fallback[0].metadata.{sensitive_key} is sensitive and must not be stored in manifests"
        in exc_info.value.errors
    )


def test_parse_model_config_rejects_empty_and_nested_fallbacks() -> None:
    """Fallback entries must identify a target and cannot recursively own fallbacks."""
    raw = _valid_model_config()
    raw["fallback"] = [{}, {"provider": "stub", "name": "safe", "fallback": []}]

    with pytest.raises(ModelConfigError) as exc_info:
        parse_model_config(raw)

    assert (
        "model.fallback[0].provider must be a non-blank string" in exc_info.value.errors
    )
    assert "model.fallback[0].name must be a non-blank string" in exc_info.value.errors
    assert "model.fallback[1].fallback is not allowed" in exc_info.value.errors


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 401 - {'error': 'x', 'sent': {'x-api-key': 'hunter2hunter2'}}",
        '{"apiKey": "hunter2hunter2"}',
        "{'api_key': 'hunter2hunter2'}",
        "{'authToken': 'hunter2hunter2'}",
        "connect https://user:hunter2hunter2@host/v1",
        "api_key=hunter2hunter2",
        "Authorization: Bearer hunter2hunter2",
        "key sk-hunter2hunter2 rejected",
    ],
)
def test_redaction_covers_the_shapes_providers_actually_emit(message: str) -> None:
    """Redaction must survive quoting, dict/JSON reprs, and URL userinfo.

    Provider SDKs surface request context as a dict or JSON repr, so a pattern
    that only accepts bare ``name=value`` walks past the most common real shape.
    Every earlier guard used the bare form, which is how that gap survived.
    """
    from backend.llm.errors import redact_error_message

    assert "hunter2hunter2" not in redact_error_message(message)


def test_global_model_config_is_absent_until_a_model_is_configured() -> None:
    """An unset global model yields no default rather than an invented one."""
    from backend.llm.registry import global_model_config

    assert global_model_config("stub", "") is None
    assert global_model_config("", "  ") is None

    configured = global_model_config("stub", "gpt-test")
    assert configured is not None
    assert (configured.provider, configured.name) == ("stub", "gpt-test")
