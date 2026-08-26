"""CRUD/upsert contract cases for every repository protocol and E51-E55 store (E56-S2-T1).

One case per repository/store, run against both backends via the fixtures
in ``conftest.py``. No backend branching in any case body.
"""

from __future__ import annotations

import uuid

from backend.environments.store import EnvironmentRecord
from backend.execution.policy import PolicyCategory, PolicyEffect, PolicyRule, PolicyScopeKind
from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy
from backend.secret_store.contracts import SecretReference
from backend.tests.persistence_contract.conftest import PlanStoreImpl, SqlStore


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


# --------------------------------------------------------------------- sessions


def test_session_repository_crud(sql_store: SqlStore) -> None:
    session_id = _uid("session")

    sql_store.create_session(session_id=session_id, goal="g", plan=["a"], artifacts={})
    assert sql_store.get_session(session_id) is not None

    sql_store.update_session_artifacts(session_id, {"note": "updated"})
    assert sql_store.get_session(session_id)["artifacts"] == {"note": "updated"}

    assert any(s["id"] == session_id for s in sql_store.list_sessions())


# --------------------------------------------------------------------- runs


def _create_session_and_run(sql_store: SqlStore) -> tuple[str, str]:
    session_id = _uid("session")
    run_id = _uid("run")
    sql_store.create_session(session_id=session_id, goal="g", plan=[], artifacts={})
    sql_store.create_run(
        run_id=run_id,
        session_id=session_id,
        status="running",
        run_type="agent",
        current_state="start",
        trigger_message="go",
        results=[],
        steps=[],
    )
    return session_id, run_id


def test_run_repository_crud(sql_store: SqlStore) -> None:
    session_id, run_id = _create_session_and_run(sql_store)

    assert sql_store.get_run(run_id) is not None

    sql_store.update_run(
        run_id=run_id,
        status="completed",
        current_state="done",
        results=[{"ok": True}],
        steps=[
            {
                "step_key": "s1",
                "agent": "a",
                "status": "done",
                "started_at": "2026-01-01T00:00:00+00:00",
                "completed_at": "2026-01-01T00:00:01+00:00",
            }
        ],
    )
    updated = sql_store.get_run(run_id)
    assert updated["status"] == "completed"
    assert updated["results"] == [{"ok": True}]

    assert any(r["id"] == run_id for r in sql_store.list_runs(session_id))


# --------------------------------------------------------------------- messages


def test_message_repository_crud(sql_store: SqlStore) -> None:
    session_id, run_id = _create_session_and_run(sql_store)

    sql_store.append_messages(
        session_id, run_id, [{"role": "user", "content": "hello"}]
    )

    messages = sql_store.list_messages(session_id)
    assert len(messages) == 1
    assert messages[0]["content"] == "hello"


# --------------------------------------------------------------------- plans


def test_plan_repository_crud(plan_store: PlanStoreImpl) -> None:
    session_id = _uid("session")

    plan_store.upsert_plan(session_id, ["step-1", "step-2"])
    plan = plan_store.get_plan(session_id)
    assert plan is not None
    assert plan.steps == ["step-1", "step-2"]

    plan_store.approve(session_id, actor="tester", note="looks good")
    approvals = plan_store.list_approvals(session_id)
    assert len(approvals) == 1
    assert approvals[0].actor == "tester"

    assert any(p.session_id == session_id for p in plan_store.list_plans())


# --------------------------------------------------------------------- eval results


def test_eval_result_repository_crud(sql_store: SqlStore) -> None:
    eval_id, eval_version, run_id = _uid("eval"), "v1", _uid("run")

    sql_store.create_eval_result(
        eval_id=eval_id, eval_version=eval_version, run_id=run_id, document={"score": 1}
    )

    result = sql_store.get_eval_result(eval_id, eval_version, run_id)
    assert result is not None
    assert result["score"] == 1

    assert sql_store.list_eval_results(eval_id, eval_version)


# --------------------------------------------------------------------- score snapshots


def test_score_snapshot_repository_crud(sql_store: SqlStore) -> None:
    snapshot_id, policy_id = _uid("snap"), _uid("policy")

    sql_store.create_score_snapshot(
        snapshot_id=snapshot_id, sample_count=10, document={"mean": 0.9}
    )
    assert sql_store.get_score_snapshot(snapshot_id) is not None

    sql_store.record_snapshot_promotion(
        policy_id=policy_id,
        snapshot_id=snapshot_id,
        baseline_snapshot_id="",
        promoted=True,
        reason="better",
        decided_at="2026-01-01T00:00:00+00:00",
    )
    assert sql_store.get_active_score_snapshot(policy_id) is not None
    assert sql_store.list_snapshot_promotions(policy_id)
    assert sql_store.list_score_snapshots()


# --------------------------------------------------------------------- E51 QuotaStore


def test_quota_store_upsert_and_get_policy(quota_store) -> None:
    tenant_id = _uid("tenant")
    policy = TenantQuotaPolicy(
        tenant_id=tenant_id,
        max_concurrent_runs=2,
        max_storage_bytes=1000,
        monthly_token_limit=1000,
        monthly_cost_microusd=1000,
        requests_per_second=1,
        default_run_budget=RunBudgetLimits(),
    )

    stored = quota_store.upsert_policy(policy)
    assert stored.version == 1

    fetched = quota_store.get_policy(tenant_id)
    assert fetched is not None
    assert fetched.max_concurrent_runs == 2


# --------------------------------------------------------------------- E52 SecretStore


def test_secret_store_create_rotate_revoke(secret_store) -> None:
    reference = SecretReference(tenant_id=_uid("tenant"), project="default", name="api-key")

    metadata = secret_store.create(reference, "ciphertext-v1")
    assert metadata.version == 1

    rotated = secret_store.rotate(reference, "ciphertext-v2")
    assert rotated.version == 2

    revoked = secret_store.revoke(reference)
    assert revoked.status.value == "revoked"


# --------------------------------------------------------------------- E53 PolicyStore


def test_policy_store_add_and_list_rules(policy_store) -> None:
    tenant_id = _uid("tenant")
    rule = PolicyRule(
        category=PolicyCategory.SHELL,
        effect=PolicyEffect.ALLOW,
        scope_kind=PolicyScopeKind.PROJECT,
        scope_id="*",
    )

    rule_id = policy_store.add_rule(tenant_id, rule)
    assert rule_id

    rules = policy_store.list_rules(tenant_id)
    assert any(r.category == PolicyCategory.SHELL for r in rules)


# --------------------------------------------------------------------- E54 EnvironmentStore


def test_environment_store_create_and_get(environment_store) -> None:
    tenant_id = _uid("tenant")
    environment_id = _uid("env")
    record = EnvironmentRecord(
        environment_id=environment_id,
        run_id=_uid("run"),
        tenant_id=tenant_id,
        backend_kind="docker",
        profile_id="default",
        profile_hash="hash",
        workspace_path="/workspace",
        status="active",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
    )

    assert environment_store.create_environment(record) is True
    fetched = environment_store.get(environment_id, tenant_id=tenant_id)
    assert fetched is not None
    assert fetched.status == "active"
    assert environment_store.count_active(tenant_id) == 1


# --------------------------------------------------------------------- E55 StepApprovalStore


def test_step_approval_store_ensure_and_get(plan_store: PlanStoreImpl, step_approval_store) -> None:
    session_id = _uid("session")
    plan_store.upsert_plan(session_id, ["do x", "do y"])

    steps = step_approval_store.ensure_steps(session_id, ["do x", "do y"])
    assert len(steps) == 2

    fetched = step_approval_store.get_step(session_id, 0)
    assert fetched is not None
    assert fetched.content == "do x"
