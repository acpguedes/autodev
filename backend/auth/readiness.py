"""Production startup gate: refuse to serve traffic without a real credential.

The legacy ``AUTODEV_API_TOKEN`` compatibility PAT deliberately does **not**
satisfy this check (ADR-018): it exists for local/single-tenant convenience,
not as a production authentication mechanism.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.auth.contracts import AuthReadinessError
from backend.auth.oidc import build_oidc_settings


def validate_auth_readiness(
    settings: Any,
    store: Any,
    *,
    now: datetime | None = None,
) -> None:
    """Refuse to start in production without a viable authentication path.

    A no-op outside the ``prod`` profile: local mode's zero-config open
    access is a deliberate, documented trust boundary (ADR-018), not
    something this check should block.

    Args:
        settings: The application :class:`~backend.config.settings.Settings`.
        store: The :class:`~backend.auth.store.AuthStore` to check for an
            active service credential.
        now: Unused; accepted for interface stability with callers that
            inject a fixed clock.

    Raises:
        AuthReadinessError: If the ``prod`` profile has neither complete
            OIDC/JWKS settings nor an active service credential.
    """
    del now
    if settings.autodev_profile != "prod":
        return
    if build_oidc_settings(settings).is_configured:
        return
    if store.has_active_service_credential():
        return
    raise AuthReadinessError(
        "Production startup requires complete OIDC/JWKS or an active "
        "service credential (docs/security.md)"
    )


__all__ = ["validate_auth_readiness"]
