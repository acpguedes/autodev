"""v2 Control Plane API — runtime configuration (E9-S1-T1).

Versions the existing ``GET``/``PUT /config`` endpoints in
``backend/api/main.py`` under ``/v2/config`` with a typed, ``schemaVersion``
-stamped envelope (E9-S1-T2). Both surfaces share the same
:class:`~backend.config.runtime.RuntimeConfigService` singleton, so a change
made through either is immediately visible to the other.

Known limitation: unlike v1's ``PUT /config`` handler, this endpoint does
not clear ``backend.api.main``'s process-wide ``get_orchestrator``/
``get_chat_model``/``get_repository_intelligence`` caches, because routers
must not import from ``main`` (see ``backend/api/routers/__init__.py``'s
auto-discovery convention — every other ``/v2`` router follows the same
rule). Those caches are invalidated the next time v1's own ``PUT /config``
runs, or on process restart. See the E9-S1 handoff notes for this
cross-surface cache-invalidation gap.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.rbac_v2 import require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2
from backend.config.runtime import RuntimeConfig, RuntimeConfigService, RuntimeInstructions, get_runtime_config_service

router = APIRouter(prefix="/v2/config", tags=["config"], dependencies=[Depends(require_v2_principal)])


class RuntimeConfigResponseV2(BaseModel):
    """Typed, versioned envelope around the runtime configuration document."""

    schemaVersion: str = SCHEMA_VERSION_V2
    config: RuntimeConfig
    instructions: RuntimeInstructions


class RuntimeConfigUpdateRequestV2(BaseModel):
    """Request body for ``PUT /v2/config``."""

    config: RuntimeConfig


@router.get("", response_model=RuntimeConfigResponseV2)
def get_runtime_config_v2(
    config_service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> RuntimeConfigResponseV2:
    """Return the current runtime configuration with secrets redacted.

    Args:
        config_service: Shared runtime config service (same singleton v1's
            ``GET /config`` uses).

    Returns:
        The versioned configuration document.
    """
    document = config_service.load_document(redact_secrets=True)
    return RuntimeConfigResponseV2(config=document.config, instructions=document.instructions)


@router.put("", response_model=RuntimeConfigResponseV2)
def update_runtime_config_v2(
    request: RuntimeConfigUpdateRequestV2,
    config_service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> RuntimeConfigResponseV2:
    """Persist a new runtime configuration and apply it to the process.

    Args:
        request: The new configuration to persist.
        config_service: Shared runtime config service (same singleton v1's
            ``PUT /config`` uses).

    Returns:
        The versioned configuration document after the update.
    """
    saved_config = config_service.update(request.config)
    config_service.apply_to_environment(saved_config)
    document = config_service.load_document(redact_secrets=True)
    return RuntimeConfigResponseV2(config=document.config, instructions=document.instructions)


__all__ = [
    "RuntimeConfigResponseV2",
    "RuntimeConfigUpdateRequestV2",
    "get_runtime_config_v2",
    "router",
    "update_runtime_config_v2",
]
