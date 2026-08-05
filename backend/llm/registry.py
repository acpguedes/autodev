"""Provider registration and deterministic model-configuration resolution."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from backend.llm.contracts import ModelProvider
from backend.llm.errors import ModelProviderNotConfiguredError
from backend.llm.model_config import ModelConfig


class ModelProviderRegistry:
    """In-memory registry keyed by stable provider identifier."""

    def __init__(self, providers: Mapping[str, ModelProvider] | None = None) -> None:
        """Initialize the registry.

        Args:
            providers: Optional initial provider-id mapping.
        """
        self._providers: dict[str, ModelProvider] = {}
        for provider_id, provider in (providers or {}).items():
            self.register(provider_id, provider)

    def register(self, provider_id: str, provider: ModelProvider) -> None:
        """Register one provider without silently replacing another.

        Args:
            provider_id: Non-blank stable provider id.
            provider: Provider adapter implementation.

        Raises:
            ValueError: If the id is blank or already registered.
        """
        normalized = provider_id.strip()
        if not normalized:
            raise ValueError("provider_id must be non-blank")
        if normalized in self._providers:
            raise ValueError(f"provider '{normalized}' is already registered")
        if not isinstance(provider, ModelProvider):
            raise TypeError(
                "provider must implement the provider-neutral ModelProvider protocol"
            )
        self._providers[normalized] = provider

    def resolve(self, provider_id: str, *, model: str | None = None) -> ModelProvider:
        """Resolve a registered provider or fail closed.

        Args:
            provider_id: Provider id to resolve.
            model: Optional model id for error correlation.

        Returns:
            Registered provider adapter.

        Raises:
            ModelProviderNotConfiguredError: If no provider is registered.
        """
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ModelProviderNotConfiguredError(
                f"provider '{provider_id}' is not configured",
                provider=provider_id,
                model=model,
            )
        return provider


def resolve_model_config(
    *,
    execution_override: ModelConfig | None = None,
    agent_config: ModelConfig | None = None,
    global_config: ModelConfig | None = None,
) -> ModelConfig:
    """Resolve execution, agent, and global model configuration precedence.

    The selected configuration is returned intact. Only its omitted provider may
    inherit from the global configuration; fallback policy is never merged from a
    lower-precedence source.

    Args:
        execution_override: Highest-precedence execution selection.
        agent_config: Agent manifest selection.
        global_config: Process-wide default selection.

    Returns:
        Effective immutable model configuration.

    Raises:
        ModelProviderNotConfiguredError: If selection or provider inheritance fails.
    """
    selected = execution_override or agent_config or global_config
    if selected is None:
        raise ModelProviderNotConfiguredError("no model provider is configured")
    if selected.provider is not None:
        return selected
    inherited = global_config.provider if global_config is not None else None
    if inherited is None:
        raise ModelProviderNotConfiguredError(
            "selected model does not declare a provider and no global provider is configured",
            model=selected.name,
        )
    return replace(selected, provider=inherited)


__all__ = ["ModelProviderRegistry", "resolve_model_config"]
