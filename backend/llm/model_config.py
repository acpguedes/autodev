"""Typed parsing and validation for provider-neutral model configuration."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence, cast

from backend.llm.contracts import (
    MODEL_CAPABILITY_IDS,
    MODEL_ERROR_CODES,
    ModelCapabilityId,
    ModelErrorCode,
)

_MODEL_KEYS = frozenset(
    {
        "provider",
        "name",
        "temperature",
        "maxTokens",
        "timeoutSeconds",
        "retries",
        "requiredCapabilities",
        "fallbackOn",
        "limits",
        "fallback",
    }
)
_TARGET_KEYS = frozenset({"provider", "name", "temperature", "maxTokens", "timeoutSeconds", "retries"})
_LIMIT_KEYS = frozenset({"maxCalls", "maxTotalTokens", "maxCostUsd"})
_SENSITIVE_KEYS = frozenset(
    {
        "apikey",
        "apitoken",
        "accesstoken",
        "authtoken",
        "bearertoken",
        "secret",
        "clientsecret",
        "password",
        "credential",
        "credentials",
        "privatekey",
    }
)


class ModelConfigError(ValueError):
    """Raised when model configuration cannot be parsed safely.

    Attributes:
        errors: All validation failures found in the configuration.
    """

    def __init__(self, errors: Sequence[str]) -> None:
        """Initialize the exception from one or more validation errors.

        Args:
            errors: Ordered validation failures.
        """
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class ModelLimits:
    """Optional aggregate limits for one configured model chain.

    Attributes:
        max_calls: Maximum provider calls across primary and fallbacks.
        max_total_tokens: Maximum aggregate input and output tokens.
        max_cost_usd: Maximum aggregate estimated cost in US dollars.
    """

    max_calls: int | None = None
    max_total_tokens: int | None = None
    max_cost_usd: float | None = None


@dataclass(frozen=True)
class ModelTarget:
    """One primary or fallback model target.

    Attributes:
        provider: Provider id, or ``None`` only for the legacy inheriting alias.
        name: Provider model id.
        temperature: Optional sampling temperature override.
        max_tokens: Optional maximum output token override.
        timeout_seconds: Optional per-attempt timeout override.
        retries: Optional retry-count override.
    """

    provider: str | None
    name: str
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    retries: int | None = None


@dataclass(frozen=True)
class ModelConfig(ModelTarget):
    """Validated model selection and governance configuration.

    Attributes:
        required_capabilities: Capabilities every selected target must provide.
        fallback_on: Normalized error codes that allow trying a fallback target.
        limits: Aggregate call, token, and cost ceilings.
        fallback: Ordered fallback targets.
    """

    retries: int | None = 0
    required_capabilities: tuple[ModelCapabilityId, ...] = ("text",)
    fallback_on: tuple[ModelErrorCode, ...] = ()
    limits: ModelLimits = field(default_factory=ModelLimits)
    fallback: tuple[ModelTarget, ...] = ()


def parse_model_config(raw: object, *, path: str = "model") -> ModelConfig:
    """Parse canonical camelCase model configuration.

    Args:
        raw: Raw manifest value for ``model``.
        path: Field path used in validation messages.

    Returns:
        Immutable validated model configuration.

    Raises:
        ModelConfigError: If any field is malformed, unknown, or sensitive.
    """
    errors: list[str] = []
    _find_sensitive_keys(raw, path=path, errors=errors)
    if not isinstance(raw, Mapping):
        errors.append(f"{path} must be an object")
        raise ModelConfigError(errors)

    _reject_unknown_keys(raw, _MODEL_KEYS, path=path, errors=errors)
    provider = _non_blank_string(raw.get("provider"), f"{path}.provider", errors)
    name = _non_blank_string(raw.get("name"), f"{path}.name", errors)
    temperature = _temperature(raw.get("temperature"), f"{path}.temperature", errors)
    max_tokens = _positive_int(raw.get("maxTokens"), f"{path}.maxTokens", errors)
    timeout_seconds = _positive_number(raw.get("timeoutSeconds"), f"{path}.timeoutSeconds", errors)
    retries = _retries(raw.get("retries", 0), f"{path}.retries", errors)
    required = _known_ids(
        raw.get("requiredCapabilities", ["text"]),
        known=MODEL_CAPABILITY_IDS,
        path=f"{path}.requiredCapabilities",
        singular="model capability",
        errors=errors,
    )
    fallback_on = _known_ids(
        raw.get("fallbackOn", []),
        known=MODEL_ERROR_CODES,
        path=f"{path}.fallbackOn",
        singular="model error",
        errors=errors,
    )
    limits = _parse_limits(raw.get("limits", {}), path=f"{path}.limits", errors=errors)
    fallback = _parse_fallback(raw.get("fallback", []), path=f"{path}.fallback", errors=errors)

    if errors:
        raise ModelConfigError(errors)
    return ModelConfig(
        provider=provider,
        name=name,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        retries=retries,
        required_capabilities=cast(tuple[ModelCapabilityId, ...], required),
        fallback_on=cast(tuple[ModelErrorCode, ...], fallback_on),
        limits=limits,
        fallback=fallback,
    )


def model_config_from_legacy_alias(name: object, *, path: str = "policy.model") -> ModelConfig:
    """Create a provider-inheriting configuration from legacy ``policy.model``.

    Args:
        name: Legacy model name.
        path: Field path used in validation messages.

    Returns:
        Configuration whose provider is inherited by the future gateway.

    Raises:
        ModelConfigError: If the legacy value is not a non-blank string.
    """
    errors: list[str] = []
    parsed_name = _non_blank_string(name, path, errors)
    if errors:
        raise ModelConfigError(errors)
    return ModelConfig(provider=None, name=parsed_name)


def _parse_limits(raw: object, *, path: str, errors: list[str]) -> ModelLimits:
    """Parse aggregate limits.

    Args:
        raw: Raw limits value.
        path: Field path used in validation messages.
        errors: Validation error accumulator.

    Returns:
        Parsed limits, using ``None`` for omitted ceilings.
    """
    if not isinstance(raw, Mapping):
        errors.append(f"{path} must be an object")
        return ModelLimits()
    _reject_unknown_keys(raw, _LIMIT_KEYS, path=path, errors=errors)
    return ModelLimits(
        max_calls=_positive_int(raw.get("maxCalls"), f"{path}.maxCalls", errors),
        max_total_tokens=_positive_int(raw.get("maxTotalTokens"), f"{path}.maxTotalTokens", errors),
        max_cost_usd=_positive_number(raw.get("maxCostUsd"), f"{path}.maxCostUsd", errors),
    )


def _parse_fallback(raw: object, *, path: str, errors: list[str]) -> tuple[ModelTarget, ...]:
    """Parse ordered non-nesting fallback targets.

    Args:
        raw: Raw fallback sequence.
        path: Field path used in validation messages.
        errors: Validation error accumulator.

    Returns:
        Parsed fallback targets; invalid entries are represented only by errors.
    """
    if not isinstance(raw, list):
        errors.append(f"{path} must be an array")
        return ()
    targets: list[ModelTarget] = []
    for index, item in enumerate(raw):
        item_path = f"{path}[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{item_path} must be an object")
            continue
        if "fallback" in item:
            errors.append(f"{item_path}.fallback is not allowed")
        _reject_unknown_keys(item, _TARGET_KEYS, path=item_path, errors=errors)
        targets.append(
            ModelTarget(
                provider=_non_blank_string(item.get("provider"), f"{item_path}.provider", errors),
                name=_non_blank_string(item.get("name"), f"{item_path}.name", errors),
                temperature=_temperature(item.get("temperature"), f"{item_path}.temperature", errors),
                max_tokens=_positive_int(item.get("maxTokens"), f"{item_path}.maxTokens", errors),
                timeout_seconds=_positive_number(
                    item.get("timeoutSeconds"), f"{item_path}.timeoutSeconds", errors
                ),
                retries=_retries(item.get("retries"), f"{item_path}.retries", errors),
            )
        )
    return tuple(targets)


def _known_ids(
    raw: object,
    *,
    known: frozenset[str],
    path: str,
    singular: str,
    errors: list[str],
) -> tuple[str, ...]:
    """Validate a list of stable vocabulary ids.

    Args:
        raw: Raw id list.
        known: Supported ids.
        path: Field path used in validation messages.
        singular: Human-readable vocabulary item name.
        errors: Validation error accumulator.

    Returns:
        String ids found in the list.
    """
    if not isinstance(raw, list):
        errors.append(f"{path} must be an array")
        return ()
    parsed: list[str] = []
    for value in raw:
        if not isinstance(value, str) or value not in known:
            errors.append(f"unknown {singular} {value}")
            continue
        parsed.append(value)
    return tuple(parsed)


def _reject_unknown_keys(
    raw: Mapping[object, object], known: frozenset[str], *, path: str, errors: list[str]
) -> None:
    """Reject fields outside the canonical camelCase syntax.

    Args:
        raw: Mapping whose keys are checked.
        known: Allowed keys.
        path: Field path used in validation messages.
        errors: Validation error accumulator.
    """
    for key in raw:
        if not isinstance(key, str) or key not in known:
            errors.append(f"{path}.{key} is not supported")


def _find_sensitive_keys(raw: object, *, path: str, errors: list[str]) -> None:
    """Recursively reject credential-like keys without inspecting their values.

    Args:
        raw: Raw configuration subtree.
        path: Current field path.
        errors: Validation error accumulator.
    """
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            child_path = f"{path}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in _SENSITIVE_KEYS:
                errors.append(f"{child_path} is sensitive and must not be stored in manifests")
            _find_sensitive_keys(value, path=child_path, errors=errors)
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            _find_sensitive_keys(value, path=f"{path}[{index}]", errors=errors)


def _non_blank_string(value: object, path: str, errors: list[str]) -> str:
    """Validate a required non-blank string.

    Args:
        value: Candidate string.
        path: Field path used in validation messages.
        errors: Validation error accumulator.

    Returns:
        Stripped string, or an empty placeholder when invalid.
    """
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path} must be a non-blank string")
        return ""
    return value.strip()


def _temperature(value: object, path: str, errors: list[str]) -> float | None:
    """Validate an optional sampling temperature.

    Args:
        value: Candidate temperature.
        path: Field path used in validation messages.
        errors: Validation error accumulator.

    Returns:
        Temperature as a float, or ``None`` when omitted or invalid.
    """
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 2
    ):
        errors.append(f"{path} must be between 0 and 2")
        return None
    return float(value)


def _positive_int(value: object, path: str, errors: list[str]) -> int | None:
    """Validate an optional positive integer.

    Args:
        value: Candidate integer.
        path: Field path used in validation messages.
        errors: Validation error accumulator.

    Returns:
        Positive integer, or ``None`` when omitted or invalid.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        errors.append(f"{path} must be a positive integer")
        return None
    return value


def _positive_number(value: object, path: str, errors: list[str]) -> float | None:
    """Validate an optional positive number.

    Args:
        value: Candidate number.
        path: Field path used in validation messages.
        errors: Validation error accumulator.

    Returns:
        Positive float, or ``None`` when omitted or invalid.
    """
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        errors.append(f"{path} must be a positive number")
        return None
    return float(value)


def _retries(value: object, path: str, errors: list[str]) -> int | None:
    """Validate an optional retry count between zero and five.

    Args:
        value: Candidate retry count.
        path: Field path used in validation messages.
        errors: Validation error accumulator.

    Returns:
        Retry count, or ``None`` when omitted or invalid.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
        errors.append(f"{path} must be an integer between 0 and 5")
        return None
    return value


__all__ = [
    "ModelConfig",
    "ModelConfigError",
    "ModelLimits",
    "ModelTarget",
    "model_config_from_legacy_alias",
    "parse_model_config",
]
