"""Typed and redacted failures for provider-neutral model execution."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.llm.contracts import ModelErrorCode

_SECRET_NAME = (
    r"api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|"
    r"secret(?:[_-]?key)?|password|credential(?:s)?"
)
# The optional quotes are load-bearing. Provider SDKs surface request context as a
# dict or JSON repr -- `{'api_key': 'v'}`, `{"x-api-key": "v"}` -- and a pattern
# that only accepts `name=value` walks straight past the most common real shape.
_ASSIGNMENT_SECRET = re.compile(
    rf"(?i)\b({_SECRET_NAME})[\"']?\s*[:=]\s*[\"']?[^\s,;'\"}}\]]+"
)
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[^\s,;\"']+")
_PROVIDER_KEY = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{6,}\b")
# Credentials also travel as URL userinfo (`https://user:secret@host`).
_URL_CREDENTIAL = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s/@:]+):[^\s/@]+@")


class ModelGatewayError(RuntimeError):
    """Base error normalized at the provider-neutral boundary.

    The defaults keep the base class usable: a provider raising the exported
    base type still carries a taxonomy-valid ``code`` instead of failing with
    ``AttributeError`` where the gateway classifies it.
    """

    code: ModelErrorCode = "provider_error"
    retryable: bool = False

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
    text = _URL_CREDENTIAL.sub(r"\1:[REDACTED]@", text)
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


KNOWN_ERROR_CODES: frozenset[str] = frozenset(
    {
        ModelProviderNotConfiguredError.code,
        ModelUnsupportedCapabilityError.code,
        ModelAuthenticationError.code,
        ModelInvalidRequestError.code,
        ModelBudgetExceededError.code,
        ModelProviderError.code,
        ModelTimeoutError.code,
        ModelRateLimitError.code,
        ModelUnavailableError.code,
    }
)
"""The stable error vocabulary, derived from the classes that define it.

Deriving this rather than restating the literals keeps it from drifting: adding a
class without adding it here is the only way to fall out of sync, and the contract
test catches that.
"""


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
    message = redact_error_message(error)
    try:
        return error_type(message, provider=provider, model=model)
    except TypeError:
        # A subclass may not accept the base constructor's keywords. Losing the
        # specific type is far better than replacing a governed failure with a
        # TypeError that escapes the taxonomy entirely -- but the code must
        # survive, or a configured `fallbackOn` for it silently stops firing.
        fallback = ModelProviderError(message, provider=provider, model=model)
        code = getattr(error, "code", None)
        if code in KNOWN_ERROR_CODES:
            fallback.code = code
        return fallback


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
