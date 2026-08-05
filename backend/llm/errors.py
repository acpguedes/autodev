"""Typed and redacted failures for provider-neutral model execution."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.llm.contracts import ModelErrorCode

_ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|"
    r"secret(?:[_-]?key)?|password|credential(?:s)?)\s*[:=]\s*[^\s,;]+"
)
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_PROVIDER_KEY = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{6,}\b")


class ModelGatewayError(RuntimeError):
    """Base error normalized at the provider-neutral boundary."""

    code: ModelErrorCode
    retryable: bool

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize a typed provider error."""
        super().__init__(message)
        self.provider = provider
        self.model = model


def redact_error_message(message: object) -> str:
    """Remove credential-like values from an exception message.

    Args:
        message: Provider exception or message to sanitize.

    Returns:
        A bounded diagnostic string with likely credential values removed.
    """
    text = str(message).replace("\n", " ")[:1000]
    text = _ASSIGNMENT_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _BEARER_SECRET.sub("Bearer [REDACTED]", text)
    return _PROVIDER_KEY.sub("[REDACTED]", text)


class ModelProviderNotConfiguredError(ModelGatewayError):
    """A referenced provider was not registered or configured."""

    code = "provider_not_configured"
    retryable = False


class ModelUnsupportedCapabilityError(ModelGatewayError):
    """A model target does not advertise a required capability."""

    code = "unsupported_capability"
    retryable = False


class ModelAuthenticationError(ModelGatewayError):
    """Provider authentication or credential configuration failed."""

    code = "authentication"
    retryable = False


class ModelInvalidRequestError(ModelGatewayError):
    """A normalized request cannot be executed by the selected target."""

    code = "invalid_request"
    retryable = False


class ModelBudgetExceededError(ModelGatewayError):
    """A configured call, token, cost, or timeout limit was exceeded."""

    code = "budget_exceeded"
    retryable = False


class ModelProviderError(ModelGatewayError):
    """An otherwise unclassified provider failure occurred."""

    code = "provider_error"
    retryable = False


class ModelTimeoutError(ModelGatewayError):
    """Provider attempt exceeded its configured timeout."""

    code = "timeout"
    retryable = True


class ModelRateLimitError(ModelGatewayError):
    """Provider rejected an attempt because of rate limiting."""

    code = "rate_limit"
    retryable = True


class ModelUnavailableError(ModelGatewayError):
    """Provider or model target was temporarily unavailable."""

    code = "unavailable"
    retryable = True


def redacted_gateway_error(
    error: BaseException,
    *,
    provider: str,
    model: str,
) -> ModelGatewayError:
    """Normalize an arbitrary failure while preserving known gateway codes.

    Args:
        error: Failure raised by a provider implementation.
        provider: Provider id for safe correlation.
        model: Model id for safe correlation.

    Returns:
        A typed gateway error with a sanitized message.
    """
    error_type: type[ModelGatewayError]
    if isinstance(error, ModelGatewayError):
        error_type = type(error)
    else:
        error_type = ModelProviderError
    return error_type(redact_error_message(error), provider=provider, model=model)


__all__ = [
    "ModelAuthenticationError",
    "ModelBudgetExceededError",
    "ModelGatewayError",
    "ModelInvalidRequestError",
    "ModelProviderError",
    "ModelProviderNotConfiguredError",
    "ModelRateLimitError",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "ModelUnsupportedCapabilityError",
    "redact_error_message",
    "redacted_gateway_error",
]
