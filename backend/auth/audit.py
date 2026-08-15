"""Required access-decision audit persistence and best-effort catalog events.

Durable persistence via :class:`AuditWriter` is authoritative (ADR-018): an
otherwise-allowed request that cannot be durably audited is denied. The
canonical ``access.request.allowed``/``access.request.denied`` events
published after a successful write are best-effort, for existing
event-driven consumers (dashboards, future audit sinks) — never the source
of truth.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from backend.auth.contracts import AccessAuditRecord
from backend.auth.store import AuthStore

logger = logging.getLogger(__name__)


def new_audit_id() -> str:
    """Generate a new, unique audit-row identifier."""
    return str(uuid.uuid4())


class AuditWriter:
    """Writes and queries the durable, tenant-scoped access-audit trail."""

    def __init__(self, store: AuthStore | None = None) -> None:
        """Build an audit writer bound to a durable Auth Store.

        Args:
            store: Durable Auth Store; defaults to a new :class:`AuthStore`.
        """
        self._store = store or AuthStore()

    def record(self, record: AccessAuditRecord, *, required: bool) -> None:
        """Durably persist one access-decision audit row.

        Args:
            record: The decision to persist.
            required: Whether the caller treats a write failure as fatal to
                the in-flight request (an about-to-be-allowed request) or
                merely logged (an already-denied request). This method
                itself always attempts the write and always propagates a
                failure — the ``required``/``not required`` distinction is
                the caller's control-flow decision, recorded here only for
                observability.

        Raises:
            Exception: Any underlying store failure.
        """
        try:
            self._store.append_access_audit(record)
        except Exception:
            logger.critical(
                "access audit write failed",
                extra={
                    "event": "security.audit_write_failed",
                    "required": required,
                    "decision": record.decision,
                    "tenant_id": record.tenant_id,
                    "route_template": record.route_template,
                    "request_id": record.request_id,
                },
                exc_info=True,
            )
            raise

    def list(
        self, *, tenant_id: str, limit: int, before: datetime | None
    ) -> list[AccessAuditRecord]:
        """List a tenant's access-audit rows, most recent first.

        Args:
            tenant_id: Tenant to scope the listing to.
            limit: Maximum rows to return.
            before: If given, only rows strictly older than this timestamp.

        Returns:
            The tenant's audit rows, most recently occurred first.
        """
        return self._store.list_access_audit(tenant_id=tenant_id, limit=limit, before=before)


_audit_writer_override: AuditWriter | None = None


def get_audit_writer() -> AuditWriter:
    """Return the process audit writer.

    Returns:
        The test-installed override, if any (see :func:`override_audit_writer`),
        otherwise a fresh :class:`AuditWriter`.
    """
    if _audit_writer_override is not None:
        return _audit_writer_override
    return AuditWriter()


def override_audit_writer(writer: AuditWriter | None) -> None:
    """Install (or clear) a process-wide audit writer override — for tests.

    Args:
        writer: The writer to install, or ``None`` to clear the override
            and resume constructing a fresh :class:`AuditWriter` per call.
    """
    global _audit_writer_override
    _audit_writer_override = writer


def publish_access_event(record: AccessAuditRecord) -> None:
    """Best-effort publish the canonical event for one durably-audited decision.

    Must be called only after :meth:`AuditWriter.record` has already
    succeeded — this function never raises and is not itself a durability
    guarantee.

    Args:
        record: The already-persisted audit row to publish.
    """
    from backend.events.catalog import AccessRequestData  # noqa: PLC0415
    from backend.events.runtime import emit_event  # noqa: PLC0415

    event_type = (
        "access.request.allowed" if record.decision == "allowed" else "access.request.denied"
    )
    payload = AccessRequestData(
        subjectId=record.subject,
        authMethod=record.auth_method.value,
        credentialId=record.credential_id,
        roles=[role.value for role in record.roles],
        requiredScope=record.required_scope,
        resourceType=record.resource_type,
        resourceId=record.resource_id,
        method=record.method,
        routeTemplate=record.route_template,
        decision=record.decision,
        reason=record.reason,
        requestId=record.request_id,
    )
    emit_event(
        event_type,
        tenant_id=record.tenant_id,
        partition_key=record.tenant_id,
        data=payload.model_dump(),
    )


__all__ = [
    "AuditWriter",
    "get_audit_writer",
    "new_audit_id",
    "override_audit_writer",
    "publish_access_event",
]
