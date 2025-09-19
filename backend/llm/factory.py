"""Factory helpers for configuring LangChain chat models."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Iterable, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

__all__ = [
    "LLMConfigurationError",
    "StubChatModel",
    "get_chat_model",
    "is_configured_model",
]


class LLMConfigurationError(RuntimeError):
    """Raised when a real LLM provider is requested but not configured."""


class StubChatModel(BaseChatModel):
    """Deterministic chat model used when no provider credentials are available."""

    model_name: str = "stub"
    is_stub: bool = True

    def __init__(self, response: str | None = None) -> None:
        super().__init__()
        self._response = response or (
            "LLM provider is not configured. Falling back to static agent messages."
        )

    @property
    def _llm_type(self) -> str:
        return "stub"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[Iterable[str]] = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Return a canned response regardless of the prompt."""

        generation = ChatGeneration(message=AIMessage(content=self._response))
        return ChatResult(generations=[generation])


def _read_temperature(value: str | None, default: float = 0.2) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError as exc:  # pragma: no cover - defensive branch
        raise LLMConfigurationError(
            "OPENAI_TEMPERATURE must be a valid float value"
        ) from exc


@lru_cache(maxsize=None)
def get_chat_model(
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    allow_stub: bool = True,
) -> BaseChatModel:
    """Return a configured ``BaseChatModel`` for the desired provider.

    Parameters
    ----------
    provider:
        Optional explicit provider name. When omitted the ``LLM_PROVIDER``
        environment variable is used and defaults to ``"stub"``.
    model:
        Optional model identifier to request from the underlying provider.
    temperature:
        Optional sampling temperature. When ``None`` the function reads the
        provider-specific environment variable.
    allow_stub:
        When ``True`` (default) the function falls back to :class:`StubChatModel`
        if the real provider cannot be configured.
    """

    resolved_provider = (provider or os.getenv("LLM_PROVIDER", "stub")).strip().lower()

    if resolved_provider in {"", "stub", "fake", "none"}:
        if not allow_stub:
            raise LLMConfigurationError("LLM provider has not been configured")
        return StubChatModel()

    if resolved_provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            if allow_stub:
                return StubChatModel()
            raise LLMConfigurationError(
                "OPENAI_API_KEY is required when using the OpenAI provider"
            )

        base_url = os.getenv("OPENAI_BASE_URL")
        resolved_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        resolved_temperature = (
            temperature
            if temperature is not None
            else _read_temperature(os.getenv("OPENAI_TEMPERATURE"), default=0.2)
        )

        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=resolved_model,
            temperature=resolved_temperature,
            api_key=api_key,
            base_url=base_url,
        )

    raise LLMConfigurationError(
        f"Unsupported LLM provider '{resolved_provider}'. Set LLM_PROVIDER to a known value."
    )


def is_configured_model(model: BaseChatModel | None) -> bool:
    """Return ``True`` if the provided model represents a real provider."""

    if model is None:
        return False
    return not getattr(model, "is_stub", False)
