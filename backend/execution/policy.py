"""Fail-closed execution policy engine (E14-S2, RFC-010/ADR-022).

Mirrors :mod:`backend.quotas.service` / :mod:`backend.quotas.store` (ADR-019):
a tenant with any stored rule is governed by exactly those rules; a tenant
with none fails closed in production and falls back to a permissive default
outside production, preserving the platform's Local-first guarantee.
"""

from __future__ import annotations

import fnmatch
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol
from uuid import uuid4

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Fallback StrEnum compatible with Python 3.10."""

        pass


from backend.config.settings import Settings, get_settings
from backend.events.runtime import emit_event
from backend.execution.contracts import ExecutionAction, ExecutionActionType

_DEFAULT_DATABASE_URL = "sqlite:///./autodev.db"


class PolicyCategory(StrEnum):
    """Action categories a policy rule can govern."""

    SHELL = "shell"
    FS_WRITE = "fs-write"
    PATCH = "patch"
    NETWORK = "network"
    SECRETS_READ = "secrets-read"
    VALIDATION = "validation"


#: Maps every :class:`ExecutionActionType` to the policy category that
#: governs it. ``network``/``secrets-read`` have no action-type source yet
#: (future runners set them); they exist so rules can be declared ahead of
#: that need, matching the taxonomy precedent in
#: :mod:`backend.plugins.permissions`.
ACTION_TYPE_TO_POLICY_CATEGORY: dict[ExecutionActionType, PolicyCategory] = {
    ExecutionActionType.CREATE_FILE: PolicyCategory.FS_WRITE,
    ExecutionActionType.EDIT_FILE: PolicyCategory.FS_WRITE,
    ExecutionActionType.APPLY_PATCH: PolicyCategory.PATCH,
    ExecutionActionType.RUN_COMMAND: PolicyCategory.SHELL,
    ExecutionActionType.RUN_VALIDATION: PolicyCategory.VALIDATION,
}


class PolicyEffect(StrEnum):
    """Whether a matching rule allows or denies an action."""

    ALLOW = "allow"
    DENY = "deny"


class PolicyScopeKind(StrEnum):
    """What a rule's ``scope_id`` identifies."""

    PROJECT = "project"
    REPOSITORY = "repository"
    SESSION = "session"


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """One allow/deny rule for a category of execution action.

    Attributes:
        category: The action category this rule governs.
        effect: Whether a match allows or denies the action.
        scope_kind: What ``scope_id`` identifies.
        scope_id: The scope this rule applies to (``"*"`` for the local
            permissive default).
        pattern: Optional glob matched against the action's first command
            token or file path; ``None`` matches any action in the category.
    """

    category: PolicyCategory
    effect: PolicyEffect
    scope_kind: PolicyScopeKind
    scope_id: str
    pattern: Optional[str] = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Outcome of evaluating one action against the resolved rule set.

    Attributes:
        allowed: Whether the action may proceed.
        matched: Whether an explicit rule (stored or dynamic) matched.
            ``False`` means no rule covers this action at all — distinct
            from an explicit ``deny`` — so callers like E14-S3's hybrid
            mode can tell "uncovered" apart from "denied."
        reason: Human-readable reason, durably recorded and returned to
            callers.
    """

    allowed: bool
    matched: bool
    reason: str


class DecisionStatus(StrEnum):
    """Lifecycle states of one pending human decision on a task (E14-S3)."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class PendingDecision:
    """One durable human-decision request, gating a task's execution.

    Attributes:
        decision_id: Unique identifier.
        tenant_id: Tenant the run belongs to.
        run_id: Orchestrator run this decision blocks.
        task_id: The plan task awaiting a decision.
        action_id: The (today, single) action derived from the task, kept
            for audit symmetry with :class:`~backend.execution.contracts.ExecutionResult`.
        category: The policy category of the blocked action.
        prompt: Human-readable description shown to the approver.
        status: Current lifecycle state.
        created_at: When the decision was requested.
        expires_at: When a still-pending decision times out.
        decided_by: Who resolved it, once resolved.
        decided_at: When it was resolved, once resolved.
        pattern: The blocked action's match target (its first command
            token or file path — see :func:`match_target`), captured at
            request time so a hybrid-mode "always" resolution can persist
            a meaningful dynamic-permission rule without re-deriving the
            original action.
    """

    decision_id: str
    tenant_id: str
    run_id: str
    task_id: str
    action_id: str
    category: PolicyCategory
    prompt: str
    status: DecisionStatus
    created_at: str
    expires_at: str
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    pattern: Optional[str] = None


class PolicyEvaluator(Protocol):
    """Anything that can gate an :class:`ExecutionAction` before dispatch."""

    def evaluate(
        self, *, tenant_id: str, action: ExecutionAction, run_id: str, actor: str = "system"
    ) -> PolicyDecision:
        """Evaluate whether *action* may proceed."""
        ...


class PolicyMissingError(RuntimeError):
    """Raised in production when a tenant has no durably stored policy rules."""

    def __init__(self, tenant_id: str) -> None:
        """Build the error for a tenant with no configured policy.

        Args:
            tenant_id: Tenant that has no stored policy rules.
        """
        super().__init__(
            f"tenant {tenant_id!r} has no durable execution policy; production "
            "requires an explicit policy (ADR-022) -- PUT /v2/execution/policy"
        )
        self.tenant_id = tenant_id


def _now() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path(database_url: str) -> Path:
    """Resolve a ``sqlite://`` URL to a filesystem path, matching the core stores."""
    url = (database_url or _DEFAULT_DATABASE_URL).strip()
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
    elif url.startswith("sqlite://"):
        raw = url.removeprefix("sqlite://")
    else:
        raise ValueError(f"PolicyStore requires a sqlite:// DATABASE_URL. Got: {url!r}")
    return Path(raw).expanduser().resolve()


class PolicyStore:
    """SQLite-backed durable store for policy rules, dynamic permissions, and audit."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Open (creating if needed) the SQLite-backed policy tables.

        Args:
            db_path: Explicit database file path; defaults to resolving
                ``DATABASE_URL``.
        """
        self._db_path = db_path or _resolve_db_path(os.environ.get("DATABASE_URL", ""))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._create_schema(conn)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS execution_policy_rules (
                rule_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                category TEXT NOT NULL,
                effect TEXT NOT NULL,
                scope_kind TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                pattern TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_execution_policy_rules_tenant
                ON execution_policy_rules(tenant_id, category);
            CREATE TABLE IF NOT EXISTS execution_dynamic_permissions (
                permission_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                category TEXT NOT NULL,
                scope_kind TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                pattern TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_execution_dynamic_permissions_tenant
                ON execution_dynamic_permissions(tenant_id, category);
            CREATE TABLE IF NOT EXISTS execution_policy_decisions (
                decision_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                category TEXT NOT NULL,
                allowed INTEGER NOT NULL,
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                decided_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_execution_policy_decisions_run
                ON execution_policy_decisions(run_id);
            CREATE TABLE IF NOT EXISTS pending_action_decisions (
                decision_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                category TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                decided_by TEXT,
                decided_at TEXT,
                pattern TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pending_action_decisions_run
                ON pending_action_decisions(run_id, task_id);
            CREATE INDEX IF NOT EXISTS idx_pending_action_decisions_tenant
                ON pending_action_decisions(tenant_id, status);
            """
        )

    def has_any_rules(self, tenant_id: str) -> bool:
        """Return whether *tenant_id* has at least one stored policy rule."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM execution_policy_rules WHERE tenant_id = ? LIMIT 1",
                (tenant_id,),
            ).fetchone()
        return row is not None

    def list_rules(self, tenant_id: str) -> list[PolicyRule]:
        """Return every stored policy rule for *tenant_id*."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, effect, scope_kind, scope_id, pattern "
                "FROM execution_policy_rules WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchall()
        return [
            PolicyRule(
                category=PolicyCategory(row["category"]),
                effect=PolicyEffect(row["effect"]),
                scope_kind=PolicyScopeKind(row["scope_kind"]),
                scope_id=row["scope_id"],
                pattern=row["pattern"],
            )
            for row in rows
        ]

    def add_rule(self, tenant_id: str, rule: PolicyRule) -> str:
        """Durably store *rule* for *tenant_id* and return its new rule id."""
        rule_id = str(uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO execution_policy_rules "
                "(rule_id, tenant_id, category, effect, scope_kind, scope_id, pattern, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rule_id,
                    tenant_id,
                    rule.category.value,
                    rule.effect.value,
                    rule.scope_kind.value,
                    rule.scope_id,
                    rule.pattern,
                    _now(),
                ),
            )
            conn.commit()
        return rule_id

    def list_dynamic_permissions(self, tenant_id: str) -> list[tuple[str, PolicyRule]]:
        """Return every dynamic permission for *tenant_id* as ``(id, rule)`` pairs."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT permission_id, category, scope_kind, scope_id, pattern "
                "FROM execution_dynamic_permissions WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchall()
        return [
            (
                row["permission_id"],
                PolicyRule(
                    category=PolicyCategory(row["category"]),
                    effect=PolicyEffect.ALLOW,
                    scope_kind=PolicyScopeKind(row["scope_kind"]),
                    scope_id=row["scope_id"],
                    pattern=row["pattern"],
                ),
            )
            for row in rows
        ]

    def add_dynamic_permission(self, tenant_id: str, rule: PolicyRule, *, actor: str) -> str:
        """Durably persist a hybrid-mode "always" grant and return its id."""
        permission_id = str(uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO execution_dynamic_permissions "
                "(permission_id, tenant_id, category, scope_kind, scope_id, pattern, created_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    permission_id,
                    tenant_id,
                    rule.category.value,
                    rule.scope_kind.value,
                    rule.scope_id,
                    rule.pattern,
                    _now(),
                    actor,
                ),
            )
            conn.commit()
        return permission_id

    def remove_dynamic_permission(self, tenant_id: str, permission_id: str) -> bool:
        """Revoke a dynamic permission; return whether a row was removed."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM execution_dynamic_permissions "
                "WHERE tenant_id = ? AND permission_id = ?",
                (tenant_id, permission_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def record_decision(
        self,
        *,
        tenant_id: str,
        run_id: str,
        action_id: str,
        category: PolicyCategory,
        allowed: bool,
        reason: str,
        actor: str,
    ) -> None:
        """Durably record one policy decision for audit."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO execution_policy_decisions "
                "(decision_id, tenant_id, run_id, action_id, category, allowed, reason, actor, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    tenant_id,
                    run_id,
                    action_id,
                    category.value,
                    1 if allowed else 0,
                    reason,
                    actor,
                    _now(),
                ),
            )
            conn.commit()

    def create_pending_decision(
        self,
        *,
        tenant_id: str,
        run_id: str,
        task_id: str,
        action_id: str,
        category: PolicyCategory,
        prompt: str,
        expires_at: str,
        pattern: Optional[str] = None,
    ) -> PendingDecision:
        """Durably create a pending human-decision request."""
        decision_id = str(uuid4())
        created_at = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pending_action_decisions "
                "(decision_id, tenant_id, run_id, task_id, action_id, category, prompt, status, "
                "created_at, expires_at, decided_by, decided_at, pattern) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)",
                (
                    decision_id,
                    tenant_id,
                    run_id,
                    task_id,
                    action_id,
                    category.value,
                    prompt,
                    DecisionStatus.PENDING.value,
                    created_at,
                    expires_at,
                    pattern,
                ),
            )
            conn.commit()
        return PendingDecision(
            decision_id=decision_id,
            tenant_id=tenant_id,
            run_id=run_id,
            task_id=task_id,
            action_id=action_id,
            category=category,
            prompt=prompt,
            status=DecisionStatus.PENDING,
            created_at=created_at,
            expires_at=expires_at,
            pattern=pattern,
        )

    def get_pending_decision(self, decision_id: str) -> Optional[PendingDecision]:
        """Fetch one pending decision by id, regardless of its status."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pending_action_decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
        return self._row_to_decision(row) if row is not None else None

    def get_decision_for_task(self, run_id: str, task_id: str) -> Optional[PendingDecision]:
        """Fetch the most recent decision request for one run's task, if any."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pending_action_decisions WHERE run_id = ? AND task_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (run_id, task_id),
            ).fetchone()
        return self._row_to_decision(row) if row is not None else None

    def list_pending_decisions(self, tenant_id: str) -> list[PendingDecision]:
        """List every still-pending decision for a tenant."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_action_decisions WHERE tenant_id = ? AND status = ?",
                (tenant_id, DecisionStatus.PENDING.value),
            ).fetchall()
        return [self._row_to_decision(row) for row in rows]

    def list_due_pending_decisions(self, *, before: str) -> list[PendingDecision]:
        """List every pending decision whose ``expires_at`` is at or before *before*."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_action_decisions WHERE status = ? AND expires_at <= ?",
                (DecisionStatus.PENDING.value, before),
            ).fetchall()
        return [self._row_to_decision(row) for row in rows]

    def resolve_pending_decision(
        self, decision_id: str, *, status: DecisionStatus, decided_by: str
    ) -> bool:
        """Resolve a pending decision; a no-op (returns ``False``) if already resolved."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE pending_action_decisions SET status = ?, decided_by = ?, decided_at = ? "
                "WHERE decision_id = ? AND status = ?",
                (status.value, decided_by, _now(), decision_id, DecisionStatus.PENDING.value),
            )
            conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_decision(row: sqlite3.Row) -> PendingDecision:
        return PendingDecision(
            decision_id=row["decision_id"],
            tenant_id=row["tenant_id"],
            run_id=row["run_id"],
            task_id=row["task_id"],
            action_id=row["action_id"],
            category=PolicyCategory(row["category"]),
            prompt=row["prompt"],
            status=DecisionStatus(row["status"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            decided_by=row["decided_by"],
            decided_at=row["decided_at"],
            pattern=row["pattern"],
        )


def match_target(action: ExecutionAction) -> str:
    """Return the string a rule's ``pattern`` glob is matched against."""
    if action.command:
        return action.command[0]
    return action.path or ""


class PolicyService:
    """Resolves tenant execution policy and evaluates actions against it."""

    def __init__(self, store: Optional[PolicyStore] = None, settings: Optional[Settings] = None) -> None:
        """Build the service over a store and settings snapshot.

        Args:
            store: Durable policy store; defaults to a fresh :class:`PolicyStore`.
            settings: Application settings; defaults to the cached settings.
        """
        self._store = store or PolicyStore()
        self._settings = settings or get_settings()

    def _local_default_rules(self) -> list[PolicyRule]:
        """Permissive allow-all default, local/dev only (ADR-022)."""
        return [
            PolicyRule(
                category=category,
                effect=PolicyEffect.ALLOW,
                scope_kind=PolicyScopeKind.PROJECT,
                scope_id="*",
                pattern=None,
            )
            for category in PolicyCategory
        ]

    def resolve_rules(self, tenant_id: str) -> list[PolicyRule]:
        """Resolve the effective rule set governing a tenant.

        Args:
            tenant_id: Tenant to resolve rules for.

        Returns:
            The tenant's stored rules, or (outside production, when none
            are stored) the permissive local default.

        Raises:
            PolicyMissingError: In production, when no stored rule exists
                for ``tenant_id``.
        """
        if self._store.has_any_rules(tenant_id):
            return self._store.list_rules(tenant_id)
        if self._settings.autodev_profile == "prod":
            raise PolicyMissingError(tenant_id)
        return self._local_default_rules()

    def set_rule(self, tenant_id: str, rule: PolicyRule) -> str:
        """Durably store one policy rule for *tenant_id* (``policy:admin``)."""
        return self._store.add_rule(tenant_id, rule)

    def list_dynamic_permissions(self, tenant_id: str) -> list[tuple[str, PolicyRule]]:
        """Return every dynamic permission granted for *tenant_id*."""
        return self._store.list_dynamic_permissions(tenant_id)

    def grant_dynamic_permission(self, tenant_id: str, rule: PolicyRule, *, actor: str) -> str:
        """Persist a hybrid-mode "always" grant (E14-S3)."""
        return self._store.add_dynamic_permission(tenant_id, rule, actor=actor)

    def revoke_dynamic_permission(self, tenant_id: str, permission_id: str) -> bool:
        """Revoke a previously granted dynamic permission."""
        return self._store.remove_dynamic_permission(tenant_id, permission_id)

    def preview(self, *, tenant_id: str, action: ExecutionAction) -> PolicyDecision:
        """Evaluate *action* without recording an audit row or emitting an event.

        Used by E14-S3's execution-mode gating to check whether an action
        is covered by policy (``matched``) before deciding whether to pause
        for a human decision — a pure, side-effect-free read.

        Args:
            tenant_id: Tenant the run belongs to.
            action: The action to preview.

        Returns:
            The decision that :meth:`evaluate` would return for the same
            inputs right now.
        """
        _category, decision = self._decide(tenant_id=tenant_id, action=action)
        return decision

    def evaluate(
        self, *, tenant_id: str, action: ExecutionAction, run_id: str, actor: str = "system"
    ) -> PolicyDecision:
        """Evaluate one action against the tenant's resolved policy.

        Args:
            tenant_id: Tenant the run belongs to.
            action: The action about to be dispatched.
            run_id: Orchestrator run this evaluation belongs to.
            actor: Who/what triggered this evaluation (defaults to
                ``"system"`` for automatic gating).

        Returns:
            The decision. Always durably recorded and always emits
            ``execution.policy.allowed``/``.denied`` before returning.
        """
        category, decision = self._decide(tenant_id=tenant_id, action=action)
        self._store.record_decision(
            tenant_id=tenant_id,
            run_id=run_id,
            action_id=action.action_id,
            category=category,
            allowed=decision.allowed,
            reason=decision.reason,
            actor=actor,
        )
        emit_event(
            "execution.policy.allowed" if decision.allowed else "execution.policy.denied",
            tenant_id=tenant_id,
            partition_key=run_id,
            data={"actionId": action.action_id, "category": category.value, "reason": decision.reason},
            subject={"runId": run_id, "taskId": action.task_id},
        )
        return decision

    def _decide(
        self, *, tenant_id: str, action: ExecutionAction
    ) -> tuple[PolicyCategory, PolicyDecision]:
        """Pure decision logic shared by :meth:`evaluate` and :meth:`preview`."""
        category = ACTION_TYPE_TO_POLICY_CATEGORY[action.type]
        rules = self.resolve_rules(tenant_id)
        dynamic = [rule for _id, rule in self._store.list_dynamic_permissions(tenant_id)]
        target = match_target(action)

        def _matches(rule: PolicyRule) -> bool:
            return rule.category is category and (
                rule.pattern is None or fnmatch.fnmatch(target, rule.pattern)
            )

        # Specificity beats scope: a dynamic (human-granted, one-off)
        # permission outranks a static rule, and a pattern-specific rule
        # outranks a category-wide one — so a hybrid-mode "always" grant for
        # one command can carve an exception out of a broader static deny,
        # and a specific static deny can still override a broad static
        # allow. Within the most specific matching tier, an explicit deny
        # wins over an allow (fail-closed tie-break).
        scored: list[tuple[int, PolicyRule]] = [
            (2 + (1 if rule.pattern is not None else 0), rule) for rule in dynamic if _matches(rule)
        ] + [(0 + (1 if rule.pattern is not None else 0), rule) for rule in rules if _matches(rule)]

        matched_rule: PolicyRule | None = None
        if scored:
            top_score = max(score for score, _rule in scored)
            top = [rule for score, rule in scored if score == top_score]
            denies = [rule for rule in top if rule.effect is PolicyEffect.DENY]
            matched_rule = denies[0] if denies else top[0]

        if matched_rule is None:
            decision = PolicyDecision(allowed=False, matched=False, reason="no matching policy rule")
        else:
            allowed = matched_rule.effect is PolicyEffect.ALLOW
            decision = PolicyDecision(
                allowed=allowed, matched=True, reason=f"{matched_rule.effect.value} rule for {category.value}"
            )

        return category, decision


__all__ = [
    "ACTION_TYPE_TO_POLICY_CATEGORY",
    "DecisionStatus",
    "PendingDecision",
    "PolicyCategory",
    "PolicyDecision",
    "PolicyEffect",
    "PolicyEvaluator",
    "PolicyMissingError",
    "PolicyRule",
    "PolicyScopeKind",
    "PolicyService",
    "PolicyStore",
    "match_target",
]
