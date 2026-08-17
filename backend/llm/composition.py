"""Composition root that wires the provider-neutral model gateway into the product.

E2-S6 delivered the gateway, its contracts, adapters and error taxonomy, but
nothing in the running system built one — every agent run fell back to the
legacy :class:`~backend.agents.provider.StubLLMProvider` branch. This module is
the missing composition step: it builds the process-wide
:class:`~backend.llm.registry.ModelProviderRegistry` and
:class:`~backend.llm.gateway.ModelGateway` singletons and hands them to
:class:`~backend.agents.runtime.AgentRuntime`.

It follows the module-level ``@lru_cache(maxsize=1)`` factory convention used
elsewhere in the backend (``get_store``/``reset_store_cache``,
``get_settings``/``reset_settings_cache``,
``get_runtime_config_service``/``reset_runtime_config_cache``) so that API
routers can depend on it directly. Routers are forbidden from importing
:mod:`backend.api.main`, which is why the composition root lives here rather
than beside the other application singletons.

Import-cycle rule (do not break this):
    :mod:`backend.config.runtime` imports :mod:`backend.llm.factory` at module
    scope. This module imports :mod:`backend.config.runtime`. Therefore this
    module **must not** be re-exported from :mod:`backend.llm` — doing so would
    close the cycle ``backend.config.runtime -> backend.llm.factory ->
    backend/llm/__init__ -> backend.llm.composition -> backend.config.runtime``
    and fail at import time. Import it by its full path instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Final

from backend.agents.runtime import AgentRuntime
from backend.config.runtime import get_runtime_config_service
from backend.config.settings import get_settings
from backend.context.composer import ContextComposer
from backend.llm.gateway import ModelGateway
from backend.llm.langchain_adapter import LangChainModelProvider
from backend.llm.model_config import ModelConfig
from backend.llm.registry import ModelProviderRegistry, global_model_config

#: Provider ids the gateway can serve in production. Every supported provider is
#: registered regardless of which one is selected, so that a manifest declaring a
#: cross-provider ``fallback`` target resolves instead of failing closed.
DEFAULT_GATEWAY_PROVIDER_IDS: Final[tuple[str, ...]] = ("openai", "ollama")


def build_model_provider_registry(
    provider_ids: Sequence[str] = DEFAULT_GATEWAY_PROVIDER_IDS,
) -> ModelProviderRegistry:
    """Build a registry holding one LangChain adapter per supported provider.

    Registering every supported provider is cheap:
    :class:`~backend.llm.langchain_adapter.LangChainModelProvider` builds no
    client and reads no credentials during construction — both are resolved
    lazily per call through :func:`backend.llm.factory.get_chat_model`.

    Args:
        provider_ids: Provider identifiers to register. Defaults to
            :data:`DEFAULT_GATEWAY_PROVIDER_IDS`.

    Returns:
        A registry with one adapter registered per requested provider id.

    Raises:
        ValueError: If an id is blank or repeated within ``provider_ids``.
        ModelInvalidRequestError: If an id is not supported by the LangChain
            adapter.
    """
    registry = ModelProviderRegistry()
    for provider_id in provider_ids:
        registry.register(provider_id, LangChainModelProvider(provider_id))
    return registry


@lru_cache(maxsize=1)
def get_model_gateway() -> ModelGateway | None:
    """Return the process-wide gateway, or ``None`` when running offline.

    ``None`` is a first-class result, not a failure. The configured provider is
    read from the runtime configuration that ``PUT /v2/provider-config`` owns.
    When it is not a real provider — the default ``stub`` profile, or an
    unrecognized value in a hand-edited config file — no gateway is built and
    :meth:`~backend.agents.runtime.AgentRuntimeContext.call_llm` keeps taking its
    existing legacy branch into
    :class:`~backend.agents.provider.StubLLMProvider`.

    That degradation is deliberate.
    :class:`~backend.llm.stub_provider.StubModelProvider` is keyed by model name
    and raises for any model it was not scripted with, so registering it as a
    production ``stub`` provider would turn the default offline profile from
    "works" into "every call fails". ``StubLLMProvider`` answers any prompt
    deterministically without network access, which is the offline guarantee the
    documentation publishes. Returning ``None`` therefore leaves the default
    profile behaviorally identical to the pre-composition system.

    An unsupported provider id degrades to ``None`` rather than raising, so a bad
    persisted config downgrades to offline instead of breaking every flow run.
    Once a supported provider *is* selected, the gateway's own fail-closed
    guarantees apply normally.

    Returns:
        The shared gateway, or ``None`` when no real provider is configured.
    """
    provider_id = get_runtime_config_service().load().llm.provider.strip().lower()
    if provider_id not in DEFAULT_GATEWAY_PROVIDER_IDS:
        return None
    return ModelGateway(build_model_provider_registry())


@lru_cache(maxsize=1)
def get_global_model_config() -> ModelConfig | None:
    """Return the process-wide default model configuration.

    The model is read from the same source the versioned API owns —
    ``RuntimeConfig.llm``, written by ``PUT /v2/provider-config`` — with the
    ``LLM_MODEL`` environment variable as an explicit operator override. That
    ordering is safe precisely because
    :meth:`~backend.config.runtime.RuntimeConfigService.apply_to_environment`
    exports the configured model as ``OPENAI_MODEL`` and never as ``LLM_MODEL``,
    so an API update can never clobber the override.

    The provider is read only from the runtime configuration.
    ``Settings.llm_provider`` is a stale snapshot by construction:
    :func:`~backend.config.settings.get_settings` is cached on first call, while
    ``apply_to_environment`` mutates ``os.environ`` afterwards.

    Returns:
        The global default, or ``None`` when no model is configured — in which
        case an agent must select its own model or the run fails explicitly.
    """
    llm = get_runtime_config_service().load().llm
    override = get_settings().llm_model.strip()
    return global_model_config(llm.provider, override or llm.model)


@lru_cache(maxsize=1)
def get_context_composer() -> ContextComposer | None:
    """Return the process-wide context composer, currently always ``None``.

    The injection seam is wired — :func:`build_agent_runtime` passes this value
    through to :class:`~backend.agents.runtime.AgentRuntime` — but no composer is
    built yet, because the surrounding plumbing cannot feed one:

    * :class:`~backend.flows.handlers.NodeContext` carries no session id, and
      ``AgentNodeHandler.__call__`` never supplies ``context_query``, so
      ``SessionMemoryContextProvider`` would return an empty list on every call.
    * ``FilesContextProvider`` requires an explicit path list, and no
      configuration surface exists to declare one.
    * :class:`~backend.context.composer.ContextComposer` requires a non-empty
      ``configs`` list and runs its providers in a thread pool, so an empty
      composer would pay a pool per agent run to produce nothing.

    Enabling context injection means threading a session id from the flow
    manifest through the run state into ``NodeContext`` and deriving a
    ``context_query`` from node input. That is a separate story, not a wiring
    fix. With the seam already in place, enabling it later changes this function
    alone.

    Returns:
        ``None`` — context injection stays disabled until the seam can be fed.
    """
    return None


def build_agent_runtime(
    *,
    tools: dict[str, Any] | None = None,
    skills: dict[str, Any] | None = None,
) -> AgentRuntime:
    """Build an agent runtime wired to the composed gateway and model config.

    The runtime itself is intentionally not cached: constructing one is trivial,
    and each handler is free to own its own. The shared, expensive artifacts —
    the gateway and the resolved global model configuration — are the cached
    ones. Sharing a single gateway across runtimes is safe because its attempt
    telemetry is thread-local.

    Args:
        tools: Optional tool implementations exposed to agents.
        skills: Optional skill implementations exposed to agents.

    Returns:
        A runtime carrying the composed gateway, global model configuration and
        context composer. When no real provider is configured the gateway is
        ``None`` and the runtime keeps its offline stub behavior.
    """
    return AgentRuntime(
        tools=tools,
        skills=skills,
        gateway=get_model_gateway(),
        model_config=get_global_model_config(),
        context_composer=get_context_composer(),
    )


def reset_model_composition_cache() -> None:
    """Clear every cached composition artifact.

    Must be called whenever the persisted LLM configuration changes, so that the
    next agent run composes against the new provider and model instead of a
    gateway built from the previous configuration. The API surfaces that write
    ``RuntimeConfig.llm`` call this after saving. Tests use it to isolate one
    configuration from the next.
    """
    get_model_gateway.cache_clear()
    get_global_model_config.cache_clear()
    get_context_composer.cache_clear()


__all__ = [
    "DEFAULT_GATEWAY_PROVIDER_IDS",
    "build_agent_runtime",
    "build_model_provider_registry",
    "get_context_composer",
    "get_global_model_config",
    "get_model_gateway",
    "reset_model_composition_cache",
]
