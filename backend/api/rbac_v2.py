"""RBAC dependency seam for the ``/v2`` Control Plane API — real since E11-S2.

Real authentication and authorization now runs as one app-level FastAPI
dependency (:func:`backend.api.authorization.enforce_control_plane_access`,
installed on :data:`backend.api.main.app`), which stores the authenticated
principal on ``request.state.principal`` before any router-level or
handler-level dependency runs. This module stays a thin re-export so every
existing ``dependencies=[Depends(require_v2_principal)]`` router and
``principal: PrincipalV2 = Depends(require_v2_principal)`` handler signature
keeps working unchanged.
"""

from __future__ import annotations

from backend.api.authorization import require_v2_principal
from backend.auth.contracts import PrincipalV2

__all__ = ["PrincipalV2", "require_v2_principal"]
