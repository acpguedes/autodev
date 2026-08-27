"""Table inventory and copy order for the SQLite -> PostgreSQL data migration (E58).

:data:`TABLE_COPY_ORDER` is the spine the rest of this package hangs off:
preflight's inventory check, the dry-run plan, the ordered copy, and
reconciliation all iterate it in this order. It was built by reading every
``CREATE TABLE`` statement in the codebase — both the versioned migration
lists (``backend/persistence/migrations/{versions,postgres_versions}.py``)
and the stores that manage their own schema idempotently outside those lists
(events, flows, auth, and the extension registries — see
``backend/persistence/contract.py``'s module docstring for why those exist).
Order respects every foreign key actually enforced in the schema; tables with
no enforced FK are grouped near the table they are conceptually part of.

This list is deliberately not treated as ground truth on its own: preflight
(:mod:`backend.persistence.sqlite_to_postgres.preflight`) diffs it against the
*source* database's actual ``sqlite_master`` table list and refuses to
proceed if an unknown table is found, so a future table this module has not
been updated for fails loudly instead of being silently dropped.
"""

from __future__ import annotations

#: Tables tracked by the versioned migration runner (``schema_version``
#: namespace ``"store"``), defined in
#: ``backend/persistence/migrations/{versions,postgres_versions}.py``.
VERSIONED_STORE_TABLES: tuple[str, ...] = (
    "sessions",
    "runs",
    "run_steps",
    "messages",
    "plugins",
    "plugin_events",
    "eval_results",
    "score_snapshots",
    "score_snapshot_promotions",
    "code_chunks",
    "code_embeddings",
    "plan_documents",
    "plan_approvals",
    "plan_step_state",
    "tenant_quota_policies",
    "tenant_usage_windows",
    "run_leases",
    "storage_reservations",
    "request_rate_buckets",
    "secrets",
    "execution_policy_rules",
    "execution_dynamic_permissions",
    "execution_policy_decisions",
    "pending_action_decisions",
    "execution_environments",
    "execution_environment_decisions",
)

#: Tables owned by stores that create their own schema idempotently
#: (``CREATE TABLE IF NOT EXISTS`` on construction, no ``schema_version``
#: tracking) rather than through the versioned migration runner.
SELF_MANAGED_TABLES: tuple[str, ...] = (
    "artifacts",
    "events",
    "event_projections",
    "flow_runs",
    "flow_steps",
    "flow_events",
    "flow_registry",
    "service_credentials",
    "auth_sessions",
    "access_audit",
    "skill_registry",
    "agent_registry",
)

#: Full copy order: every table this migrator knows how to move, in an order
#: that satisfies every foreign key enforced in the schema (``runs`` ->
#: ``sessions``; ``run_steps`` -> ``runs``; ``messages`` -> ``sessions``,
#: ``runs``; ``code_embeddings`` -> ``code_chunks``; ``plan_step_state`` ->
#: ``plan_documents``). Tables with no enforced FK are placed next to the
#: table they are conceptually part of.
TABLE_COPY_ORDER: tuple[str, ...] = VERSIONED_STORE_TABLES + SELF_MANAGED_TABLES

#: SQLite-internal tables that are never part of the migrated data, even
#: though they appear in ``sqlite_master``.
IGNORED_SQLITE_TABLES: frozenset[str] = frozenset(
    {"schema_version", "sqlite_sequence"}
)

__all__ = [
    "IGNORED_SQLITE_TABLES",
    "SELF_MANAGED_TABLES",
    "TABLE_COPY_ORDER",
    "VERSIONED_STORE_TABLES",
]
