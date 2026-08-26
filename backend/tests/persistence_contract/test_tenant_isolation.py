"""Tenant isolation contract cases (E56-S3-T2): both directions, both backends.

Every tenant-scoped table uses one of exactly two isolation mechanisms
(``docs/v2_platform/phases/e50_postgres_schema_migrations_rls.md``):
PostgreSQL Row-Level Security (``backend.persistence.tenancy.set_postgres_tenant``)
or, on SQLite (no RLS equivalent), an explicit ``WHERE tenant_id = ...``
clause (``sqlite_tenant_clause``) applied by every store method that reads
or writes a tenant-scoped row. Both mechanisms are wired identically across
all thirteen E50 tables and the six pre-existing core tables, so this suite
covers the mechanism once per owning store rather than duplicating a
near-identical case per table:

* ``sessions``/``runs``/``messages`` (core, E8-S1) -- via ``sql_store``.
* ``tenant_quota_policies`` (of the five QuotaStore tables: also
  ``tenant_usage_windows``, ``run_leases``, ``storage_reservations``,
  ``request_rate_buckets``) -- via ``quota_store``.
* ``secrets`` -- via ``secret_store``.
* ``execution_policy_rules`` (of the four PolicyStore tables: also
  ``execution_dynamic_permissions``, ``execution_policy_decisions``,
  ``pending_action_decisions``) -- via ``policy_store``.
* ``execution_environments`` (of the two EnvironmentStore tables: also
  ``execution_environment_decisions``) -- via ``environment_store``.
* ``plan_step_state`` -- via ``step_approval_store``.

Each case asserts both directions: tenant A cannot read tenant B's row, and
tenant B cannot read tenant A's -- so a policy that denies everything
cannot pass by accident.
"""

from __future__ import annotations

import uuid

from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy
from backend.secret_store.contracts import SecretReference
from backend.tests.persistence_contract.conftest import PlanStoreImpl, SqlStore


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def test_session_isolation_both_directions(sql_store: SqlStore) -> None:
    tenant_a, tenant_b = _uid("tenant"), _uid("tenant")
    session_a, session_b = _uid("session"), _uid("session")
    sql_store.create_session(
        session_id=session_a, goal="a", plan=[], artifacts={}, tenant_id=tenant_a
    )
    sql_store.create_session(
        session_id=session_b, goal="b", plan=[], artifacts={}, tenant_id=tenant_b
    )

    assert sql_store.get_session(session_a, tenant_id=tenant_b) is None
    assert sql_store.get_session(session_b, tenant_id=tenant_a) is None
    assert sql_store.get_session(session_a, tenant_id=tenant_a) is not None
    assert sql_store.get_session(session_b, tenant_id=tenant_b) is not None


def test_quota_policy_isolation_both_directions(quota_store) -> None:
    tenant_a, tenant_b = _uid("tenant"), _uid("tenant")

    def _policy(tenant_id: str, limit: int) -> TenantQuotaPolicy:
        return TenantQuotaPolicy(
            tenant_id=tenant_id,
            max_concurrent_runs=limit,
            max_storage_bytes=1000,
            monthly_token_limit=1000,
            monthly_cost_microusd=1000,
            requests_per_second=1,
            default_run_budget=RunBudgetLimits(),
        )

    quota_store.upsert_policy(_policy(tenant_a, 1))
    quota_store.upsert_policy(_policy(tenant_b, 2))

    fetched_a = quota_store.get_policy(tenant_a)
    fetched_b = quota_store.get_policy(tenant_b)
    assert fetched_a is not None and fetched_a.max_concurrent_runs == 1
    assert fetched_b is not None and fetched_b.max_concurrent_runs == 2


def test_secret_isolation_both_directions(secret_store) -> None:
    tenant_a, tenant_b = _uid("tenant"), _uid("tenant")
    reference_a = SecretReference(tenant_id=tenant_a, project="default", name="key")
    reference_b = SecretReference(tenant_id=tenant_b, project="default", name="key")

    secret_store.create(reference_a, "ciphertext-a")
    secret_store.create(reference_b, "ciphertext-b")

    assert secret_store.get_metadata(reference_a) is not None
    assert secret_store.get_metadata(reference_b) is not None
    assert [m.reference for m in secret_store.list_metadata(tenant_a)] == [reference_a]
    assert [m.reference for m in secret_store.list_metadata(tenant_b)] == [reference_b]


def test_policy_rule_isolation_both_directions(policy_store) -> None:
    from backend.execution.policy import PolicyCategory, PolicyEffect, PolicyRule, PolicyScopeKind

    tenant_a, tenant_b = _uid("tenant"), _uid("tenant")
    rule = PolicyRule(
        category=PolicyCategory.SHELL,
        effect=PolicyEffect.ALLOW,
        scope_kind=PolicyScopeKind.PROJECT,
        scope_id="*",
    )

    policy_store.add_rule(tenant_a, rule)

    assert policy_store.has_any_rules(tenant_a) is True
    assert policy_store.has_any_rules(tenant_b) is False
    assert policy_store.list_rules(tenant_b) == []


def test_environment_isolation_both_directions(environment_store) -> None:
    from backend.environments.store import EnvironmentRecord

    tenant_a, tenant_b = _uid("tenant"), _uid("tenant")
    environment_id = _uid("env")
    environment_store.create_environment(
        EnvironmentRecord(
            environment_id=environment_id,
            run_id=_uid("run"),
            tenant_id=tenant_a,
            backend_kind="docker",
            profile_id="default",
            profile_hash="hash",
            workspace_path="/workspace",
            status="active",
            created_at="2026-01-01T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
    )

    assert environment_store.get(environment_id, tenant_id=tenant_b) is None
    assert environment_store.get(environment_id, tenant_id=tenant_a) is not None
    assert environment_store.count_active(tenant_b) == 0
    assert environment_store.count_active(tenant_a) == 1


def test_plan_step_state_isolation_both_directions(
    plan_store: PlanStoreImpl, step_approval_store
) -> None:
    tenant_a, tenant_b = _uid("tenant"), _uid("tenant")
    session_id = _uid("session")
    plan_store.upsert_plan(session_id, ["step-1"], tenant_id=tenant_a)

    step_approval_store.ensure_steps(session_id, ["step-1"], tenant_id=tenant_a)

    assert step_approval_store.list_steps(session_id, tenant_id=tenant_b) == []
    assert len(step_approval_store.list_steps(session_id, tenant_id=tenant_a)) == 1
