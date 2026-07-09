"""v2 Control Plane API — provider configuration and live status (E16-S4-T4).

A versioned successor, scoped to the LLM provider settings, of the legacy
root-relative ``config`` surface (``frontend/lib/api.ts::getRuntimeConfig`` /
``updateRuntimeConfig``). Backed by the same
:class:`~backend.config.runtime.RuntimeConfigService` singleton
``/v2/config`` (E9-S1-T1) uses, so a change made through either surface is
immediately visible to the other.

``GET /v2/provider-config/status`` additionally derives a simple live health
signal (name, model, configured/healthy) from the stored provider settings —
E5's full routing/provider-selection machinery is not invoked here per the
story's explicit "do not over-engineer" guidance; a local provider (stub,
ollama) is always considered configured, while a remote provider (e.g.
openai) is considered configured once it has an API key or base URL.

Known limitation: like ``/v2/config``, this endpoint's ``PUT`` handler does
not clear ``backend.api.main``'s process-wide caches, because routers must
not import from ``main`` (see ``backend/api/routers/__init__.py``'s
auto-discovery convention).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.rbac_v2 import require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2
from backend.config.runtime import LLMSettings, RuntimeConfigService, get_runtime_config_service

router = APIRouter(prefix="/v2/provider-config", tags=["provider-config"], dependencies=[Depends(require_v2_principal)])

# Providers that are considered "configured" without any credential, because
# they run against a local or stubbed backend.
_LOCAL_PROVIDERS = {"stub", "ollama"}


class ProviderConfigResponseV2(BaseModel):
    """Typed, versioned envelope around the LLM provider configuration."""

    schemaVersion: str = SCHEMA_VERSION_V2
    llm: LLMSettings


class ProviderConfigUpdateRequestV2(BaseModel):
    """Request body for ``PUT /v2/provider-config``."""

    llm: LLMSettings


class ProviderStatusResponseV2(BaseModel):
    """Live provider status for the shell's sidebar provider card."""

    schemaVersion: str = SCHEMA_VERSION_V2
    name: str
    model: str
    configured: bool
    healthy: bool


def _redacted_llm(config_service: RuntimeConfigService) -> LLMSettings:
    """Load the current LLM settings with the API key redacted."""
    return config_service.load_document(redact_secrets=True).config.llm


@router.get("", response_model=ProviderConfigResponseV2)
def get_provider_config_v2(
    config_service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> ProviderConfigResponseV2:
    """Return the current LLM provider configuration with the API key redacted.

    Args:
        config_service: Shared runtime config service.

    Returns:
        The versioned provider configuration.
    """
    return ProviderConfigResponseV2(llm=_redacted_llm(config_service))


@router.put("", response_model=ProviderConfigResponseV2)
def update_provider_config_v2(
    request: ProviderConfigUpdateRequestV2,
    config_service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> ProviderConfigResponseV2:
    """Persist new LLM provider settings and apply them to the process.

    The request is scoped to ``llm`` only; the currently stored
    ``repository`` settings are preserved unchanged. Echoing back the
    redaction placeholder for ``api_key`` preserves the previously stored
    secret (:meth:`RuntimeConfigService.update`).

    Args:
        request: The new LLM provider settings to persist.
        config_service: Shared runtime config service.

    Returns:
        The versioned provider configuration after the update.
    """
    current = config_service.load()
    merged = current.model_copy(update={"llm": request.llm})
    saved_config = config_service.update(merged)
    config_service.apply_to_environment(saved_config)
    return ProviderConfigResponseV2(llm=_redacted_llm(config_service))


@router.get("/status", response_model=ProviderStatusResponseV2)
def get_provider_status_v2(
    config_service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> ProviderStatusResponseV2:
    """Return a live provider status derived from the stored provider settings.

    Args:
        config_service: Shared runtime config service.

    Returns:
        The provider's name, model, and a simple configured/healthy signal.
    """
    llm = config_service.load().llm
    configured = llm.provider in _LOCAL_PROVIDERS or bool(llm.api_key) or bool(llm.base_url)
    return ProviderStatusResponseV2(name=llm.provider, model=llm.model, configured=configured, healthy=configured)


__all__ = [
    "ProviderConfigResponseV2",
    "ProviderConfigUpdateRequestV2",
    "ProviderStatusResponseV2",
    "get_provider_config_v2",
    "get_provider_status_v2",
    "router",
    "update_provider_config_v2",
]
