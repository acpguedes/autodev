"""v2 Control Plane API — tenant-scoped access-audit retrieval (E11-S2 Task 4)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.api.authorization import requires_scope
from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.auth.audit import get_audit_writer

router = APIRouter(prefix="/v2/audit", tags=["audit"])

_MAX_LIMIT = 200


class AccessAuditEntryV2(BaseModel):
    """One access-decision audit row, as returned by ``GET /v2/audit/access``."""

    model_config = ConfigDict(populate_by_name=True)

    audit_id: str = Field(alias="auditId")
    occurred_at: str = Field(alias="occurredAt")
    subject: str
    auth_method: str = Field(alias="authMethod")
    credential_id: str | None = Field(default=None, alias="credentialId")
    roles: list[str]
    required_scope: str = Field(alias="requiredScope")
    resource_type: str = Field(alias="resourceType")
    resource_id: str | None = Field(default=None, alias="resourceId")
    method: str
    route_template: str = Field(alias="routeTemplate")
    decision: str
    reason: str
    request_id: str = Field(alias="requestId")


class AccessAuditListV2(BaseModel):
    """Paginated collection of :class:`AccessAuditEntryV2`."""

    items: list[AccessAuditEntryV2]


@requires_scope("audit:read")
@router.get("/access", response_model=AccessAuditListV2)
def list_access_audit_v2(
    limit: int = Query(default=50, ge=1, le=_MAX_LIMIT),
    before: datetime | None = Query(default=None),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> AccessAuditListV2:
    """List the caller's tenant's access-decision audit trail.

    Args:
        limit: Maximum rows to return, capped at 200.
        before: If given, only rows strictly older than this timestamp.
        principal: The authenticated caller; its tenant is the only tenant
            this endpoint can ever query — no request parameter selects a
            different one.

    Returns:
        The tenant's audit rows, most recently occurred first.
    """
    rows = get_audit_writer().list(
        tenant_id=principal.tenant_id, limit=min(limit, _MAX_LIMIT), before=before
    )
    return AccessAuditListV2(
        items=[
            AccessAuditEntryV2(
                auditId=row.audit_id,
                occurredAt=row.occurred_at.isoformat(),
                subject=row.subject,
                authMethod=row.auth_method.value,
                credentialId=row.credential_id,
                roles=[role.value for role in row.roles],
                requiredScope=row.required_scope,
                resourceType=row.resource_type,
                resourceId=row.resource_id,
                method=row.method,
                routeTemplate=row.route_template,
                decision=row.decision,
                reason=row.reason,
                requestId=row.request_id,
            )
            for row in rows
        ]
    )


__all__ = ["AccessAuditEntryV2", "AccessAuditListV2", "router"]
