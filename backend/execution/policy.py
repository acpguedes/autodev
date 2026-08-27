"""Fail-closed execution policy engine (E14-S2, RFC-010/ADR-022).

Mirrors :mod:`backend.quotas.service` / :mod:`backend.quotas.store` (ADR-019):
a tenant with any stored rule is governed by exactly those rules; a tenant
with none fails closed in production and falls back to a permissive default
outside production, preserving the platform's Local-first guarantee.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol
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
from backend.persistence import contract
from backend.persistence.database import get_store
from backend.persistence.tenancy import set_postgres_tenant


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


def _iso(value: Any) -> Any:
    """Normalize a possibly-``datetime`` row value to an ISO-8601 string.

    SQLite returns ``TEXT`` timestamp columns as plain strings, but psycopg
    deserializes PostgreSQL's ``TIMESTAMPTZ`` columns into ``datetime``
    objects -- without this, :class:`PendingDecision`'s ``str``-typed
    timestamp fields (compared as strings in
    :meth:`~backend.execution.decisions.DecisionService._maybe_expire`)
    would silently hold a different type per backend (E57).

    Args:
        value: A row value, either already a string/``None`` or a ``datetime``.

    Returns:
        *value* unchanged, or its ISO-8601 string form if it was a ``datetime``.
    """
    return value.isoformat() if isinstance(value, datetime) else value


#: Column order for a full ``pending_action_decisions`` row, shared by every
#: ``SELECT`` that reads a whole row and by :meth:`PolicyStore._row_to_decision`
#: -- explicit rather than ``SELECT *`` so positional indexing (required for
#: a query to read identically on SQLite's ``sqlite3.Row`` and a PostgreSQL
#: cursor's plain tuple) never depends on each backend's own column order.
_PENDING_DECISION_COLUMNS = (
    "decision_id, tenant_id, run_id, task_id, action_id, category, prompt, "
    "status, created_at, expires_at, decided_by, decided_at, pattern"
)


class PolicyStore:
    """Durable store for policy rules, dynamic permissions, and decision audit.

    Runs on both SQLite and PostgreSQL through the shared persistence
    contract (E49, ADR-025; E53), following the same port pattern
    :class:`~backend.quotas.store.QuotaStore` (E51) and
    :class:`~backend.secret_store.store.SecretStore` (E52) established. The
    ``pending_action_decisions`` terminal transition
    (:meth:`resolve_pending_decision`) is a single state-guarded conditional
    ``UPDATE`` (``WHERE ... AND status = 'pending'``) rather than a
    read-then-write pair: unlike the phantom-row races E51/E52 closed with a
    ``pg_advisory_xact_lock`` (counting existing rows, then conditionally
    inserting a new one), this transition only ever touches a row that
    already exists, so PostgreSQL's own row-level locking on the ``UPDATE``
    statement is already sufficient -- a concurrent second ``UPDATE`` blocks
    until the first commits, then re-evaluates its ``WHERE`` clause against
    the now-committed ``status`` and matches zero rows.

    All four tables carry Row-Level Security on PostgreSQL (E50-S4): every
    tenant-scoped operation calls
    :func:`~backend.persistence.tenancy.set_postgres_tenant` via
    :meth:`PolicyStore._scope` (a no-op on SQLite, which has no RLS and is
    scoped by the ``WHERE tenant_id = ...`` clauses already present in each
    query). :meth:`list_due_pending_decisions` is a deliberate exception,
    documented on the method itself.
    """

    def __init__(self, db_path: Optional[Path] = None, *, store: Any = None) -> None:
        """Open the store against an explicit SQLite file, an injected store, or the configured one.

        Args:
            db_path: When given (and ``store`` is not), a SQLite file to open
                directly -- built into a dedicated
                :class:`~backend.persistence.sqlite_adapter.store.SQLiteStore`
                so tests can exercise real, independently-connected SQLite
                instances against the same file.
            store: An existing store exposing ``connect()`` (a
                :class:`~backend.persistence.sqlite_adapter.store.SQLiteStore`
                or ``PostgresStore``). Takes precedence over ``db_path``.
                Defaults to the process-wide configured store
                (:func:`backend.persistence.database.get_store`) when neither
                is given -- the path production takes.

        Raises:
            TypeError: If the resolved store does not expose ``connect()``.
        """
        if store is None and db_path is not None:
            from backend.persistence.sqlite_adapter.store import SQLiteStore  # noqa: PLC0415

            store = SQLiteStore(f"sqlite:///{db_path}")
        self._store = store or get_store()
        if not hasattr(self._store, "connect"):
            raise TypeError("PolicyStore requires a durable store with connect()")

    # --------------------------------------------------------------- helpers

    @property
    def _is_postgres(self) -> bool:
        """Whether the backing store is a PostgreSQL database."""
        return contract.is_postgres(getattr(self._store, "database_url", ""))

    def _sql(self, template: str) -> str:
        """Substitute this store's dialect placeholder into a SQL template."""
        return contract.sql(template, self._is_postgres)

    def _connect(self) -> Any:
        """Open a fresh connection from the backing store."""
        return self._store.connect()

    def _begin_write(self, conn: Any) -> None:
        """Start a write transaction eagerly on SQLite; a no-op on PostgreSQL."""
        contract.begin_write(conn, self._is_postgres)

    def _scope(self, conn: Any, tenant_id: str) -> None:
        """Set the PostgreSQL tenant GUC for this transaction; a no-op on SQLite."""
        if self._is_postgres:
            set_postgres_tenant(conn, tenant_id)

    # ---------------------------------------------------------------- rules

    def has_any_rules(self, tenant_id: str) -> bool:
        """Return whether *tenant_id* has at least one stored policy rule."""
        conn = self._connect()
        self._scope(conn, tenant_id)
        row = conn.execute(
            self._sql("SELECT 1 FROM execution_policy_rules WHERE tenant_id = {p} LIMIT 1"),
            (tenant_id,),
        ).fetchone()
        return row is not None

    def list_rules(self, tenant_id: str) -> list[PolicyRule]:
        """Return every stored policy rule for *tenant_id*."""
        conn = self._connect()
        self._scope(conn, tenant_id)
        rows = conn.execute(
            self._sql(
                "SELECT category, effect, scope_kind, scope_id, pattern "
                "FROM execution_policy_rules WHERE tenant_id = {p}"
            ),
            (tenant_id,),
        ).fetchall()
        return [
            PolicyRule(
                category=PolicyCategory(row[0]),
                effect=PolicyEffect(row[1]),
                scope_kind=PolicyScopeKind(row[2]),
                scope_id=row[3],
                pattern=row[4],
            )
            for row in rows
        ]

    def add_rule(self, tenant_id: str, rule: PolicyRule) -> str:
        """Durably store *rule* for *tenant_id* and return its new rule id."""
        rule_id = str(uuid4())
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO execution_policy_rules "
                    "(rule_id, tenant_id, category, effect, scope_kind, scope_id, pattern, created_at) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"
                ),
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

    # ---------------------------------------------------- dynamic permissions

    def list_dynamic_permissions(self, tenant_id: str) -> list[tuple[str, PolicyRule]]:
        """Return every dynamic permission for *tenant_id* as ``(id, rule)`` pairs."""
        conn = self._connect()
        self._scope(conn, tenant_id)
        rows = conn.execute(
            self._sql(
                "SELECT permission_id, category, scope_kind, scope_id, pattern "
                "FROM execution_dynamic_permissions WHERE tenant_id = {p}"
            ),
            (tenant_id,),
        ).fetchall()
        return [
            (
                row[0],
                PolicyRule(
                    category=PolicyCategory(row[1]),
                    effect=PolicyEffect.ALLOW,
                    scope_kind=PolicyScopeKind(row[2]),
                    scope_id=row[3],
                    pattern=row[4],
                ),
            )
            for row in rows
        ]

    def add_dynamic_permission(self, tenant_id: str, rule: PolicyRule, *, actor: str) -> str:
        """Durably persist a hybrid-mode "always" grant and return its id."""
        permission_id = str(uuid4())
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO execution_dynamic_permissions "
                    "(permission_id, tenant_id, category, scope_kind, scope_id, pattern, created_at, created_by) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"
                ),
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
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            cursor = conn.execute(
                self._sql(
                    "DELETE FROM execution_dynamic_permissions "
                    "WHERE tenant_id = {p} AND permission_id = {p}"
                ),
                (tenant_id, permission_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    # --------------------------------------------------------- decision audit

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
        """Durably record one policy decision for audit.

        Append-only: no method updates or deletes a row in
        ``execution_policy_decisions`` once written (E53-S2).
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO execution_policy_decisions "
                    "(decision_id, tenant_id, run_id, action_id, category, allowed, reason, actor, decided_at) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"
                ),
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

    # ------------------------------------------------------ pending decisions

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
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            conn.execute(
                self._sql(
                    "INSERT INTO pending_action_decisions "
                    "(decision_id, tenant_id, run_id, task_id, action_id, category, prompt, status, "
                    "created_at, expires_at, decided_by, decided_at, pattern) "
                    "VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, NULL, NULL, {p})"
                ),
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

    def get_pending_decision(self, decision_id: str, *, tenant_id: str) -> Optional[PendingDecision]:
        """Fetch one pending decision by id, regardless of its status.

        Args:
            decision_id: The decision to fetch.
            tenant_id: Caller's tenant. Required (rather than checked after
                the fact) so the query is scoped identically on both
                backends: an explicit ``WHERE tenant_id = ...`` predicate on
                SQLite, and the same predicate plus Row-Level Security on
                PostgreSQL (:meth:`_scope`) -- a decision belonging to
                another tenant is indistinguishable from a nonexistent one.
        """
        conn = self._connect()
        self._scope(conn, tenant_id)
        row = conn.execute(
            self._sql(
                f"SELECT {_PENDING_DECISION_COLUMNS} FROM pending_action_decisions "
                "WHERE decision_id = {p} AND tenant_id = {p}"
            ),
            (decision_id, tenant_id),
        ).fetchone()
        return self._row_to_decision(row) if row is not None else None

    def get_decision_for_task(
        self, run_id: str, task_id: str, *, tenant_id: str
    ) -> Optional[PendingDecision]:
        """Fetch the most recent decision request for one run's task, if any.

        Args:
            run_id: The run the task belongs to.
            task_id: The task awaiting (or that awaited) a decision.
            tenant_id: Caller's tenant, scoping the lookup the same way
                :meth:`get_pending_decision` does.
        """
        conn = self._connect()
        self._scope(conn, tenant_id)
        row = conn.execute(
            self._sql(
                f"SELECT {_PENDING_DECISION_COLUMNS} FROM pending_action_decisions "
                "WHERE tenant_id = {p} AND run_id = {p} AND task_id = {p} "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            (tenant_id, run_id, task_id),
        ).fetchone()
        return self._row_to_decision(row) if row is not None else None

    def list_pending_decisions(self, tenant_id: str) -> list[PendingDecision]:
        """List every still-pending decision for a tenant."""
        conn = self._connect()
        self._scope(conn, tenant_id)
        rows = conn.execute(
            self._sql(
                f"SELECT {_PENDING_DECISION_COLUMNS} FROM pending_action_decisions "
                "WHERE tenant_id = {p} AND status = {p}"
            ),
            (tenant_id, DecisionStatus.PENDING.value),
        ).fetchall()
        return [self._row_to_decision(row) for row in rows]

    def list_due_pending_decisions(self, *, before: str) -> list[PendingDecision]:
        """List every pending decision whose ``expires_at`` is at or before *before*.

        Deliberately cross-tenant, for the operator/cron expiry sweep
        (:meth:`~backend.execution.decisions.DecisionService.expire_due`):
        there is no single tenant to scope this query to. On SQLite (no
        Row-Level Security) this reads every tenant's due decisions, same as
        before the port. On PostgreSQL, this intentionally does not set the
        ``app.tenant_id`` GUC -- with Row-Level Security forced, the result
        reflects whatever the connection's ambient tenant scope already is,
        which is empty for an unscoped connection, so this returns no rows
        until a superuser/``BYPASSRLS`` administrative path exists. This is
        the same documented scope boundary
        :meth:`~backend.quotas.store.QuotaStore.list_tenant_ids` accepted in
        E51 for the equivalent cross-tenant enumeration; solving it requires
        an administrative connection path, not a persistence-port concern
        for this epic.

        Args:
            before: ISO-8601 cutoff; a decision expiring at or before this
                instant is due.
        """
        conn = self._connect()
        rows = conn.execute(
            self._sql(
                f"SELECT {_PENDING_DECISION_COLUMNS} FROM pending_action_decisions "
                "WHERE status = {p} AND expires_at <= {p}"
            ),
            (DecisionStatus.PENDING.value, before),
        ).fetchall()
        return [self._row_to_decision(row) for row in rows]

    def resolve_pending_decision(
        self, decision_id: str, *, status: DecisionStatus, decided_by: str, tenant_id: str
    ) -> bool:
        """Atomically resolve a pending decision to a terminal state (E53-S2).

        A single state-guarded conditional ``UPDATE``
        (``WHERE decision_id = ... AND tenant_id = ... AND status =
        'pending'``): exactly one concurrent caller's ``UPDATE`` can ever
        affect this row, because the second caller's ``UPDATE`` blocks on
        the row lock the first holds, then -- once the first commits --
        re-evaluates its own ``WHERE`` clause against the now-committed
        ``status`` and matches zero rows. No caller-side check-then-write is
        involved; the atomicity is the single statement's own guarantee, on
        both backends.

        Args:
            decision_id: The decision to resolve.
            status: The terminal status to record.
            decided_by: Who resolved it.
            tenant_id: Caller's tenant, scoping the update the same way
                :meth:`get_pending_decision` scopes its read.

        Returns:
            ``True`` if this call performed the transition (the decision was
            still pending); ``False`` if it was already resolved (by this
            call's own tenant filter finding nothing pending, whether
            because another caller won the race or because the decision
            never existed for this tenant) -- callers distinguish "already
            resolved" from "resolved to what I wanted" via a follow-up read.
        """
        with self._connect() as conn:
            self._scope(conn, tenant_id)
            self._begin_write(conn)
            cursor = conn.execute(
                self._sql(
                    "UPDATE pending_action_decisions SET status = {p}, decided_by = {p}, decided_at = {p} "
                    "WHERE decision_id = {p} AND tenant_id = {p} AND status = {p}"
                ),
                (
                    status.value,
                    decided_by,
                    _now(),
                    decision_id,
                    tenant_id,
                    DecisionStatus.PENDING.value,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_decision(row: tuple) -> PendingDecision:
        """Build a :class:`PendingDecision` from a row shaped like :data:`_PENDING_DECISION_COLUMNS`."""
        return PendingDecision(
            decision_id=row[0],
            tenant_id=row[1],
            run_id=row[2],
            task_id=row[3],
            action_id=row[4],
            category=PolicyCategory(row[5]),
            prompt=row[6],
            status=DecisionStatus(row[7]),
            created_at=_iso(row[8]),
            expires_at=_iso(row[9]),
            decided_by=row[10],
            decided_at=_iso(row[11]),
            pattern=row[12],
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
