"""Secret lifecycle service: crypto + store + durable audit (E33-S1/S3, ADR-014).

:class:`SecretService` is the boundary every caller (REST router, CLI,
injection path) goes through -- it never lets a plaintext value leave
without going through :mod:`backend.secret_store.crypto`, and it emits the
``secret.*`` audit events for every create/rotate/revoke/resolve so the
audit trail (E33-S3-T2) needs no separate wiring at each call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.config.settings import Settings, get_settings
from backend.events.runtime import emit_event
from backend.secret_store.contracts import SecretMetadata, SecretReference
from backend.secret_store.crypto import decrypt_secret_value, encrypt_secret_value
from backend.secret_store.store import SecretStore


@dataclass(frozen=True, slots=True)
class SecretHandle:
    """A secret reference paired with its currently resolved plaintext value.

    Returned only by :meth:`SecretService.resolve_for_injection` -- the
    sole call site permitted to hold a plaintext value, and only for the
    duration of injecting it into an execution environment (E33-S2).
    """

    reference: SecretReference
    value: str
    metadata: SecretMetadata


class SecretService:
    """Tenant-scoped secret lifecycle operations over the durable store."""

    def __init__(
        self, store: Optional[SecretStore] = None, settings: Optional[Settings] = None
    ) -> None:
        """Build the service over a store and settings snapshot.

        Args:
            store: Durable secret store; defaults to a fresh
                :class:`~backend.secret_store.store.SecretStore`.
            settings: Application settings; defaults to the cached settings.
        """
        self._store = store or SecretStore()
        self._settings = settings or get_settings()

    def create(self, reference: SecretReference, value: str, *, actor_id: str) -> SecretMetadata:
        """Create the first version of a new secret.

        Args:
            reference: Scoped reference to create.
            value: Raw secret value; encrypted before it ever reaches the store.
            actor_id: Authenticated caller performing this operation (audit only).

        Returns:
            The stored version's metadata.
        """
        ciphertext = encrypt_secret_value(value, settings=self._settings)
        metadata = self._store.create(reference, ciphertext)
        self._audit("secret.created", metadata, actor_id=actor_id)
        return metadata

    def rotate(self, reference: SecretReference, value: str, *, actor_id: str) -> SecretMetadata:
        """Store a new version of an existing secret.

        Args:
            reference: Scoped reference to rotate.
            value: Raw new secret value; encrypted before it ever reaches the store.
            actor_id: Authenticated caller performing this operation (audit only).

        Returns:
            The new version's metadata.
        """
        ciphertext = encrypt_secret_value(value, settings=self._settings)
        metadata = self._store.rotate(reference, ciphertext)
        self._audit("secret.rotated", metadata, actor_id=actor_id)
        return metadata

    def revoke(self, reference: SecretReference, *, actor_id: str) -> SecretMetadata:
        """Revoke a secret, failing all future resolution closed.

        Args:
            reference: Scoped reference to revoke.
            actor_id: Authenticated caller performing this operation (audit only).

        Returns:
            The revoked version's metadata.
        """
        metadata = self._store.revoke(reference)
        self._audit("secret.revoked", metadata, actor_id=actor_id)
        return metadata

    def get_metadata(self, reference: SecretReference) -> Optional[SecretMetadata]:
        """Return a secret's latest version's metadata, never a value."""
        return self._store.get_metadata(reference)

    def list_metadata(
        self, tenant_id: str, *, project: Optional[str] = None
    ) -> list[SecretMetadata]:
        """List a tenant's secrets' latest-version metadata, never values."""
        return self._store.list_metadata(tenant_id, project=project)

    def resolve_for_injection(self, reference: SecretReference, *, actor_id: str) -> SecretHandle:
        """Resolve a secret's live plaintext value for environment injection only.

        Only :mod:`backend.environments.manager` (E33-S2) should call this.
        Every resolution is durably audited (``secret.resolved``, E33-S3-T2)
        before the value is handed back, so the audit trail reconstructs
        who/what resolved which reference when, without ever recording the
        value itself.

        Args:
            reference: Scoped reference to resolve.
            actor_id: Identifier of the caller resolving this secret (e.g.
                the environment/run id), for audit only.

        Returns:
            The resolved handle carrying the plaintext value.

        Raises:
            SecretNotFoundError: If no version exists for ``reference``.
            SecretRevokedError: If the latest version was revoked.
        """
        ciphertext, metadata = self._store.resolve_latest_active(reference)
        value = decrypt_secret_value(ciphertext, settings=self._settings)
        self._audit("secret.resolved", metadata, actor_id=actor_id)
        return SecretHandle(reference=reference, value=value, metadata=metadata)

    def _audit(self, event_type: str, metadata: SecretMetadata, *, actor_id: str) -> None:
        emit_event(
            event_type,
            tenant_id=metadata.reference.tenant_id,
            partition_key=metadata.reference.tenant_id,
            data={
                "tenantId": metadata.reference.tenant_id,
                "project": metadata.reference.project,
                "name": metadata.reference.name,
                "version": metadata.version,
                "actorId": actor_id,
            },
            subject={
                "tenantId": metadata.reference.tenant_id,
                "secretRef": metadata.reference.as_key(),
            },
        )


__all__ = ["SecretHandle", "SecretService"]
