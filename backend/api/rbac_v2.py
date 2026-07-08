"""RBAC dependency seam for the ``/v2`` Control Plane API (E9-S1-T3).

Role-based access control for ``/v2`` is delegated to E11 (see reference doc
§18.7.3); this module defines only the dependency *seam* new v2 routers
attach to today, so E11 can later swap in real authorization without
changing any router's signature.

Bearer-token authentication (independent of roles) is unaffected by this
module: it is already enforced globally, for every route including these,
by :func:`backend.api.security.require_api_token` (a no-op unless
``AUTODEV_API_TOKEN`` is configured). This module adds no new authentication
— it is a permissive placeholder for *authorization* only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Request


@dataclass(slots=True)
class PrincipalV2:
    """Placeholder authenticated principal until E11 introduces real RBAC.

    Attributes:
        subject: Caller identifier. Always ``"anonymous"`` until real
            authentication is wired in by E11.
        roles: Roles granted to the caller. Always ``("*",)`` (all roles)
            until real authorization is wired in by E11.
    """

    subject: str = "anonymous"
    roles: tuple[str, ...] = field(default_factory=lambda: ("*",))


def require_v2_principal(request: Request) -> PrincipalV2:
    """No-op RBAC dependency: passthrough until E11 wires real authorization.

    Every new ``/v2`` router added for E9-S1 depends on this function at the
    router level so the seam is visible and discoverable; it currently
    grants every caller a permissive placeholder principal regardless of
    *request*.

    Args:
        request: The incoming request (unused; accepted so the seam's
            signature already matches what a real RBAC dependency will need,
            e.g. to inspect headers or path parameters).

    Returns:
        A permissive placeholder :class:`PrincipalV2`.
    """
    del request
    return PrincipalV2()


__all__ = ["PrincipalV2", "require_v2_principal"]
