"""v2 Control Plane API — scoped secret references (E33-S1, ADR-014).

Every response model here carries metadata only -- no field can ever hold
a stored value, so "no API returns a stored value" holds structurally,
not just by handler-code discipline.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.api.authorization import requires_scope
from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.api.v2_common import SCHEMA_VERSION_V2, v2_error
from backend.secret_store.contracts import SecretMetadata, SecretNotFoundError, SecretReference
from backend.secret_store.service import SecretService

router = APIRouter(prefix="/v2/secrets", tags=["secrets"], dependencies=[Depends(require_v2_principal)])


def get_secret_service() -> SecretService:
    """Build a :class:`SecretService` bound to the shared durable store.

    Constructed fresh per request, matching every other ``/v2`` router's
    service-provider convention (see ``quotas_v2.get_quota_service``).

    Returns:
        A new :class:`SecretService`.
    """
    return SecretService()


class SecretMetadataV2(BaseModel):
    """A secret's latest-version metadata, as exposed over the API. Never a value."""

    model_config = ConfigDict(populate_by_name=True)

    schemaVersion: str = SCHEMA_VERSION_V2
    project: str
    name: str
    version: int
    status: str
    createdAt: str
    rotatedAt: str | None = None
    revokedAt: str | None = None

    @classmethod
    def from_metadata(cls, metadata: SecretMetadata) -> "SecretMetadataV2":
        """Build the API model from a domain :class:`SecretMetadata`."""
        return cls(
            project=metadata.reference.project,
            name=metadata.reference.name,
            version=metadata.version,
            status=metadata.status.value,
            createdAt=metadata.created_at,
            rotatedAt=metadata.rotated_at,
            revokedAt=metadata.revoked_at,
        )


class SecretListV2(BaseModel):
    """A tenant's secrets, metadata only."""

    schemaVersion: str = SCHEMA_VERSION_V2
    secrets: list[SecretMetadataV2]


class CreateSecretRequestV2(BaseModel):
    """Request body for ``POST /v2/secrets``."""

    model_config = ConfigDict(populate_by_name=True)

    project: str = "default"
    name: str
    value: str = Field(description="Raw secret value; encrypted before storage, never echoed back.")


class RotateSecretRequestV2(BaseModel):
    """Request body for ``POST /v2/secrets/{project}/{name}/rotate``."""

    value: str = Field(description="Raw new secret value; encrypted before storage, never echoed back.")


@requires_scope("secret:manage")
@router.post("", response_model=SecretMetadataV2, status_code=201)
def create_secret_v2(
    request: CreateSecretRequestV2,
    secret_service: SecretService = Depends(get_secret_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> SecretMetadataV2:
    """Create the first version of a new secret, scoped to the caller's own tenant.

    Args:
        request: The secret's scope and raw value.
        secret_service: Secret service dependency.
        principal: Authenticated caller (must hold ``secret:manage``); its
            tenant is the only tenant this endpoint can ever write.

    Returns:
        The stored version's metadata.

    Raises:
        HTTPException: 409 if a secret already exists at this reference.
    """
    reference = SecretReference(
        tenant_id=principal.tenant_id, project=request.project, name=request.name
    )
    try:
        metadata = secret_service.create(reference, request.value, actor_id=principal.subject)
    except ValueError as exc:
        v2_error(409, str(exc))
    return SecretMetadataV2.from_metadata(metadata)


@requires_scope("secret:manage")
@router.post("/{project}/{name}/rotate", response_model=SecretMetadataV2)
def rotate_secret_v2(
    project: str,
    name: str,
    request: RotateSecretRequestV2,
    secret_service: SecretService = Depends(get_secret_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> SecretMetadataV2:
    """Store a new version of an existing secret.

    Args:
        project: The secret's project scope.
        name: The secret's name.
        request: The new raw value.
        secret_service: Secret service dependency.
        principal: Authenticated caller (must hold ``secret:manage``).

    Returns:
        The new version's metadata.

    Raises:
        HTTPException: 404 if no secret exists at this reference.
    """
    reference = SecretReference(tenant_id=principal.tenant_id, project=project, name=name)
    try:
        metadata = secret_service.rotate(reference, request.value, actor_id=principal.subject)
    except SecretNotFoundError as exc:
        v2_error(404, str(exc))
    return SecretMetadataV2.from_metadata(metadata)


@requires_scope("secret:manage")
@router.post("/{project}/{name}/revoke", response_model=SecretMetadataV2)
def revoke_secret_v2(
    project: str,
    name: str,
    secret_service: SecretService = Depends(get_secret_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> SecretMetadataV2:
    """Revoke a secret, failing all future resolution closed.

    Args:
        project: The secret's project scope.
        name: The secret's name.
        secret_service: Secret service dependency.
        principal: Authenticated caller (must hold ``secret:manage``).

    Returns:
        The revoked version's metadata.

    Raises:
        HTTPException: 404 if no secret exists at this reference.
    """
    reference = SecretReference(tenant_id=principal.tenant_id, project=project, name=name)
    try:
        metadata = secret_service.revoke(reference, actor_id=principal.subject)
    except SecretNotFoundError as exc:
        v2_error(404, str(exc))
    return SecretMetadataV2.from_metadata(metadata)


@requires_scope("secret:use")
@router.get("", response_model=SecretListV2)
def list_secrets_v2(
    project: str | None = None,
    secret_service: SecretService = Depends(get_secret_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> SecretListV2:
    """List the caller's own tenant's secrets, metadata only.

    Args:
        project: Optional project to further scope the listing.
        secret_service: Secret service dependency.
        principal: Authenticated caller; its tenant is the only tenant this
            endpoint can ever query.

    Returns:
        The tenant's secrets' metadata.
    """
    metadata_list = secret_service.list_metadata(principal.tenant_id, project=project)
    return SecretListV2(secrets=[SecretMetadataV2.from_metadata(item) for item in metadata_list])


@requires_scope("secret:use")
@router.get("/{project}/{name}", response_model=SecretMetadataV2)
def get_secret_v2(
    project: str,
    name: str,
    secret_service: SecretService = Depends(get_secret_service),
    principal: PrincipalV2 = Depends(require_v2_principal),
) -> SecretMetadataV2:
    """Return one secret's latest-version metadata, never its value.

    Args:
        project: The secret's project scope.
        name: The secret's name.
        secret_service: Secret service dependency.
        principal: Authenticated caller; its tenant is the only tenant this
            endpoint can ever query.

    Returns:
        The secret's latest-version metadata.

    Raises:
        HTTPException: 404 if no secret exists at this reference.
    """
    reference = SecretReference(tenant_id=principal.tenant_id, project=project, name=name)
    metadata = secret_service.get_metadata(reference)
    if metadata is None:
        v2_error(404, f"no secret at {reference.as_key()!r}")
    return SecretMetadataV2.from_metadata(metadata)


__all__ = [
    "CreateSecretRequestV2",
    "RotateSecretRequestV2",
    "SecretListV2",
    "SecretMetadataV2",
    "create_secret_v2",
    "get_secret_service",
    "get_secret_v2",
    "list_secrets_v2",
    "revoke_secret_v2",
    "rotate_secret_v2",
    "router",
]
