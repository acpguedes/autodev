"""Human decision requests gating execution-mode pauses (E14-S3).

Reuses the durable ``pending_action_decisions`` table added to
:class:`~backend.execution.policy.PolicyStore` (the same durability concern
as its dynamic-permission table) and the existing
``run.human.requested``/``run.human.resolved`` events — no new event types
were needed for this story.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from backend.config.settings import Settings, get_settings
from backend.events.runtime import emit_event
from backend.execution.contracts import ExecutionAction
from backend.execution.policy import DecisionStatus, PendingDecision, PolicyCategory, PolicyStore


class DecisionNotFoundError(LookupError):
    """Raised when a decision id does not exist for the caller's tenant."""

    def __init__(self, decision_id: str) -> None:
        """Build the error for a decision id not found under the caller's tenant."""
        super().__init__(f"No pending decision {decision_id!r} for this tenant")
        self.decision_id = decision_id


class DecisionAlreadyResolvedError(RuntimeError):
    """Raised when attempting to resolve a decision that is no longer pending."""

    def __init__(self, decision_id: str) -> None:
        """Build the error for a decision that was already resolved."""
        super().__init__(f"Decision {decision_id!r} has already been resolved")
        self.decision_id = decision_id


def _default_now() -> datetime:
    """Return the current UTC time; the service's default clock."""
    return datetime.now(timezone.utc)


class DecisionService:
    """Requests, resolves, and expires human decisions on execution tasks."""

    def __init__(
        self,
        store: Optional[PolicyStore] = None,
        settings: Optional[Settings] = None,
        *,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        """Build the service over a store, settings, and an injectable clock.

        Args:
            store: Durable decision store; defaults to a fresh
                :class:`~backend.execution.policy.PolicyStore`.
            settings: Application settings; defaults to the cached settings.
            now: Clock used for expiry math; defaults to the real UTC clock.
                Tests inject a fixed/controllable clock (matching the
                ``Callable[[], datetime]`` convention already used by
                ``backend.flows.human``).
        """
        self._store = store or PolicyStore()
        self._settings = settings or get_settings()
        self._now = now or _default_now

    def request(
        self,
        *,
        tenant_id: str,
        run_id: str,
        task_id: str,
        action: ExecutionAction,
        category: PolicyCategory,
        prompt: str,
        pattern: Optional[str] = None,
    ) -> PendingDecision:
        """Request (or return the already-existing) decision for one task.

        Idempotent: a task with an existing decision for this run returns
        that decision — self-expiring it first if its deadline has already
        passed — rather than creating a duplicate.

        Args:
            tenant_id: Tenant the run belongs to.
            run_id: The run the blocked task belongs to.
            task_id: The task awaiting a decision.
            action: The (today, single) action the task derived.
            category: The action's policy category.
            prompt: Human-readable description shown to the approver.
            pattern: The action's match target, captured so a hybrid-mode
                "always" resolution can persist a meaningful dynamic
                permission without re-deriving the action later.
        """
        existing = self._store.get_decision_for_task(run_id, task_id)
        if existing is not None:
            return self._maybe_expire(existing)
        expires_at = (
            self._now() + timedelta(seconds=self._settings.autodev_execution_decision_timeout_seconds)
        ).isoformat()
        decision = self._store.create_pending_decision(
            tenant_id=tenant_id,
            run_id=run_id,
            task_id=task_id,
            action_id=action.action_id,
            category=category,
            prompt=prompt,
            expires_at=expires_at,
            pattern=pattern,
        )
        emit_event(
            "run.human.requested",
            tenant_id=tenant_id,
            partition_key=run_id,
            data={"stepKey": task_id, "prompt": prompt},
            subject={"runId": run_id, "taskId": task_id},
        )
        return decision

    def get_for_task(self, run_id: str, task_id: str) -> Optional[PendingDecision]:
        """Return the decision for one run's task, self-expiring it if due."""
        existing = self._store.get_decision_for_task(run_id, task_id)
        return self._maybe_expire(existing) if existing is not None else None

    def resolve(
        self, decision_id: str, *, tenant_id: str, decision: DecisionStatus, actor: str
    ) -> PendingDecision:
        """Resolve a pending decision to ``APPROVED`` or ``DENIED``.

        Args:
            decision_id: The decision to resolve.
            tenant_id: Caller's tenant — must match the decision's tenant.
            decision: Either :attr:`DecisionStatus.APPROVED` or
                :attr:`DecisionStatus.DENIED`.
            actor: Who resolved it.

        Returns:
            The resolved decision.

        Raises:
            DecisionNotFoundError: If no such decision exists for this tenant.
            DecisionAlreadyResolvedError: If it was already resolved
                (including a concurrent timeout discovered on read).
        """
        pending = self._store.get_pending_decision(decision_id)
        if pending is None or pending.tenant_id != tenant_id:
            raise DecisionNotFoundError(decision_id)
        pending = self._maybe_expire(pending)
        if pending.status is not DecisionStatus.PENDING:
            raise DecisionAlreadyResolvedError(decision_id)
        ok = self._store.resolve_pending_decision(decision_id, status=decision, decided_by=actor)
        if not ok:
            raise DecisionAlreadyResolvedError(decision_id)
        emit_event(
            "run.human.resolved",
            tenant_id=tenant_id,
            partition_key=pending.run_id,
            data={"stepKey": pending.task_id, "decision": decision.value},
            subject={"runId": pending.run_id, "taskId": pending.task_id},
        )
        resolved = self._store.get_pending_decision(decision_id)
        assert resolved is not None  # just resolved above; must exist
        return resolved

    def expire_due(self, *, at: Optional[str] = None) -> list[PendingDecision]:
        """Expire every pending decision whose deadline has passed (operator/cron sweep).

        A timed-out decision's fallback is the story's documented default:
        deny, and the orchestrator stops processing further tasks in that
        run when it observes a ``TIMED_OUT`` decision.

        Args:
            at: ISO-8601 cutoff; defaults to the service's current time.

        Returns:
            The decisions just transitioned to :attr:`DecisionStatus.TIMED_OUT`.
        """
        cutoff = at or self._now().isoformat()
        due = self._store.list_due_pending_decisions(before=cutoff)
        expired: list[PendingDecision] = []
        for pending in due:
            ok = self._store.resolve_pending_decision(
                pending.decision_id, status=DecisionStatus.TIMED_OUT, decided_by="system:timeout"
            )
            if not ok:
                continue
            emit_event(
                "run.human.resolved",
                tenant_id=pending.tenant_id,
                partition_key=pending.run_id,
                data={"stepKey": pending.task_id, "decision": DecisionStatus.TIMED_OUT.value},
                subject={"runId": pending.run_id, "taskId": pending.task_id},
            )
            refreshed = self._store.get_pending_decision(pending.decision_id)
            if refreshed is not None:
                expired.append(refreshed)
        return expired

    def list_pending(self, tenant_id: str) -> list[PendingDecision]:
        """List every still-pending decision for a tenant, self-expiring due ones first."""
        self.expire_due(at=self._now().isoformat())
        return self._store.list_pending_decisions(tenant_id)

    def _maybe_expire(self, pending: PendingDecision) -> PendingDecision:
        """Self-expire *pending* in place if its deadline has already passed."""
        if pending.status is not DecisionStatus.PENDING:
            return pending
        if pending.expires_at > self._now().isoformat():
            return pending
        self.expire_due(at=self._now().isoformat())
        refreshed = self._store.get_pending_decision(pending.decision_id)
        return refreshed if refreshed is not None else pending


__all__ = ["DecisionAlreadyResolvedError", "DecisionNotFoundError", "DecisionService"]
