"""Unit tests for the model-gateway composition root (E2-S6 wiring).

These cover the decisions the composition root encodes: that the offline
``stub`` profile deliberately yields no gateway, that every supported provider
is registered so cross-provider fallback targets resolve, that the global model
configuration reads the source the versioned API owns, and that the caches are
invalidated when configuration changes.

No test here issues a model call, so none touches the network.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.config.runtime import (
    LLMSettings,
    get_runtime_config_service,
    reset_runtime_config_cache,
)
from backend.config.settings import reset_settings_cache
from backend.llm.composition import (
    DEFAULT_GATEWAY_PROVIDER_IDS,
    build_agent_runtime,
    build_model_provider_registry,
    get_context_composer,
    get_global_model_config,
    get_model_gateway,
    reset_model_composition_cache,
)
from backend.llm.errors import ModelInvalidRequestError, ModelProviderNotConfiguredError
from backend.llm.gateway import ModelGateway
from backend.llm.model_config import ModelConfig


def _persist_llm_settings(provider: str, model: str) -> None:
    """Persist an LLM configuration and invalidate the composition caches.

    Args:
        provider: Provider id to store in the runtime configuration.
        model: Model name to store in the runtime configuration.
    """
    service = get_runtime_config_service()
    current = service.load()
    service.update(current.model_copy(update={"llm": LLMSettings(provider=provider, model=model)}))
    reset_model_composition_cache()


@pytest.fixture
def clean_composition() -> Iterator[None]:
    """Reset every composition and settings cache around a single test.

    Yields:
        ``None``. The reset is ambient for the duration of the test.
    """
    reset_model_composition_cache()
    reset_settings_cache()
    yield
    reset_model_composition_cache()
    reset_settings_cache()
    reset_runtime_config_cache()


class TestGatewayComposition:
    """Behavior of :func:`get_model_gateway`."""

    def test_stub_profile_composes_no_gateway(self, clean_composition: None) -> None:
        """The offline default must not build a gateway.

        ``StubModelProvider`` is keyed by model name and raises for unscripted
        models, so composing it as a production provider would break every call.
        Returning ``None`` keeps the legacy ``StubLLMProvider`` branch, which
        answers any prompt offline.
        """
        _persist_llm_settings("stub", "irrelevant")
        assert get_model_gateway() is None

    def test_real_provider_composes_a_gateway(self, clean_composition: None) -> None:
        """A supported provider yields a usable gateway."""
        _persist_llm_settings("openai", "gpt-4o-mini")
        assert isinstance(get_model_gateway(), ModelGateway)

    def test_unsupported_provider_degrades_to_offline(self, clean_composition: None) -> None:
        """A bad persisted provider degrades instead of breaking every run."""
        _persist_llm_settings("not-a-real-provider", "whatever")
        assert get_model_gateway() is None

    def test_provider_id_is_matched_case_insensitively(self, clean_composition: None) -> None:
        """Provider ids are normalized before the supported-provider check."""
        _persist_llm_settings("OpenAI", "gpt-4o-mini")
        assert isinstance(get_model_gateway(), ModelGateway)

    def test_gateway_is_memoized(self, clean_composition: None) -> None:
        """Repeated calls share one gateway; a reset builds a new one."""
        _persist_llm_settings("openai", "gpt-4o-mini")
        first = get_model_gateway()
        assert get_model_gateway() is first
        reset_model_composition_cache()
        assert get_model_gateway() is not first


class TestProviderRegistry:
    """Behavior of :func:`build_model_provider_registry`."""

    def test_every_supported_provider_is_registered(self) -> None:
        """Cross-provider fallback targets must resolve, so all ids register."""
        registry = build_model_provider_registry()
        for provider_id in DEFAULT_GATEWAY_PROVIDER_IDS:
            assert registry.resolve(provider_id) is not None

    def test_unregistered_provider_fails_closed(self) -> None:
        """Resolving an unregistered provider raises rather than guessing."""
        registry = build_model_provider_registry()
        with pytest.raises(ModelProviderNotConfiguredError):
            registry.resolve("anthropic")

    def test_unsupported_provider_id_is_rejected(self) -> None:
        """The adapter rejects ids it cannot serve."""
        with pytest.raises(ModelInvalidRequestError):
            build_model_provider_registry(("openai", "not-a-real-provider"))

    def test_duplicate_provider_id_is_rejected(self) -> None:
        """Registration never silently replaces an existing provider."""
        with pytest.raises(ValueError):
            build_model_provider_registry(("openai", "openai"))


class TestGlobalModelConfig:
    """Behavior of :func:`get_global_model_config`."""

    def test_reads_the_model_the_versioned_api_owns(self, clean_composition: None) -> None:
        """The model comes from ``RuntimeConfig.llm``, not the orphan setting.

        This is the regression guard for the original defect: an operator who
        set the model through ``PUT /v2/provider-config`` left ``LLM_MODEL``
        empty, so the global config resolved to ``None`` and every agent without
        a manifest-level model failed.
        """
        _persist_llm_settings("ollama", "llama3.1")
        assert get_global_model_config() == ModelConfig(provider="ollama", name="llama3.1")

    def test_env_override_wins_over_the_persisted_model(
        self, clean_composition: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``LLM_MODEL`` is an explicit operator override."""
        monkeypatch.setenv("LLM_MODEL", "override-model")
        reset_settings_cache()
        _persist_llm_settings("openai", "persisted-model")
        assert get_global_model_config() == ModelConfig(provider="openai", name="override-model")

    def test_blank_override_defers_to_the_persisted_model(
        self, clean_composition: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whitespace-only override is treated as unset, not as a model name."""
        monkeypatch.setenv("LLM_MODEL", "   ")
        reset_settings_cache()
        _persist_llm_settings("openai", "persisted-model")
        assert get_global_model_config() == ModelConfig(provider="openai", name="persisted-model")

    def test_provider_comes_from_the_runtime_config(self, clean_composition: None) -> None:
        """The provider is never read from the cached ``Settings`` snapshot."""
        _persist_llm_settings("ollama", "llama3.1")
        config = get_global_model_config()
        assert config is not None
        assert config.provider == "ollama"


class TestRuntimeComposition:
    """Behavior of :func:`build_agent_runtime` and the composer seam."""

    def test_context_composer_stays_disabled(self) -> None:
        """The seam is wired but cannot be fed yet, so it composes nothing."""
        assert get_context_composer() is None

    def test_runtime_carries_the_composed_gateway(self, clean_composition: None) -> None:
        """A configured provider reaches the runtime through composition."""
        _persist_llm_settings("openai", "gpt-4o-mini")
        runtime = build_agent_runtime()
        assert runtime._gateway is get_model_gateway()
        assert runtime._model_config == get_global_model_config()

    def test_offline_runtime_keeps_the_legacy_stub_path(self, clean_composition: None) -> None:
        """With no real provider the runtime is unchanged from before wiring."""
        _persist_llm_settings("stub", "irrelevant")
        runtime = build_agent_runtime()
        assert runtime._gateway is None

    def test_runtime_is_not_memoized(self, clean_composition: None) -> None:
        """Runtimes are cheap and per-handler; only the shared parts are cached."""
        _persist_llm_settings("openai", "gpt-4o-mini")
        assert build_agent_runtime() is not build_agent_runtime()
