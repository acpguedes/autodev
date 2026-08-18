"""Typed contracts for the Beta secret store abstraction (E33-S1, ADR-014).

Defines the scoped :class:`SecretReference` every operation is keyed by and
the metadata-only :class:`SecretMetadata` every read returns. No contract in
this module ever carries a plaintext value -- see ``backend.secret_store.store``
for the one write-only/injection-only boundary that does.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Fallback StrEnum compatible with Python 3.10."""

        pass


class SecretBackendKind(StrEnum):
    """Persistence backends selectable behind the E33 secret-store abstraction.

    ``ENCRYPTED_DATABASE`` is the Beta default recommended by ADR-014
    (envelope-encrypted values in the durable store). The enum stays
    extensible so a future external KMS/vault backend (ADR-014's other
    option) plugs in without a contract change.
    """

    ENCRYPTED_DATABASE = "encrypted_database"


class SecretStatus(StrEnum):
    """Lifecycle status of one stored secret version."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class SecretReference:
    """Scoped identifier every secret operation is keyed by -- never a value.

    Attributes:
        tenant_id: Tenant that owns the secret.
        project: Logical grouping within the tenant (e.g. a repository or
            environment-profile id); ``"default"`` when the caller has no
            finer scope to declare.
        name: The secret's name within ``tenant_id/project``.
    """

    tenant_id: str
    project: str
    name: str

    def __post_init__(self) -> None:
        """Reject an empty scope component.

        Raises:
            ValueError: If any of ``tenant_id``/``project``/``name`` is
                empty.
        """
        for field_name, value in (
            ("tenant_id", self.tenant_id),
            ("project", self.project),
            ("name", self.name),
        ):
            if not value:
                raise ValueError(f"{field_name} must be a non-empty string")

    def as_key(self) -> str:
        """Return the stable ``tenant/project/name`` string form of this reference."""
        return f"{self.tenant_id}/{self.project}/{self.name}"


@dataclass(frozen=True, slots=True)
class SecretMetadata:
    """Durable metadata for one secret version -- never a value.

    Attributes:
        reference: The scoped reference this metadata describes.
        version: Monotonically increasing version number, starting at 1.
        status: The version's current lifecycle status.
        backend_kind: The backend that persisted this version.
        created_at: ISO-8601 UTC creation timestamp.
        rotated_at: ISO-8601 UTC timestamp of the rotation that superseded
            this version, if any.
        revoked_at: ISO-8601 UTC timestamp this version was revoked, if any.
    """

    reference: SecretReference
    version: int
    status: SecretStatus
    backend_kind: SecretBackendKind
    created_at: str
    rotated_at: str | None = None
    revoked_at: str | None = None


class SecretNotFoundError(LookupError):
    """Raised when a referenced secret has no active version to resolve."""

    def __init__(self, reference: SecretReference) -> None:
        """Build the error for a missing reference.

        Args:
            reference: The scoped reference that could not be resolved.
        """
        super().__init__(f"no active secret for {reference.as_key()!r}")
        self.reference = reference


class SecretRevokedError(RuntimeError):
    """Raised when resolution is attempted against a revoked reference.

    Resolution fails closed: a revoked secret never resolves to its old
    value again, even transiently.
    """

    def __init__(self, reference: SecretReference, *, revoked_at: str) -> None:
        """Build the error for a revoked reference.

        Args:
            reference: The scoped reference that was revoked.
            revoked_at: ISO-8601 UTC timestamp of the revocation.
        """
        super().__init__(f"secret {reference.as_key()!r} was revoked at {revoked_at}")
        self.reference = reference
        self.revoked_at = revoked_at


__all__ = [
    "SecretBackendKind",
    "SecretMetadata",
    "SecretNotFoundError",
    "SecretReference",
    "SecretRevokedError",
    "SecretStatus",
]
