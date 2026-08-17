"""Concurrent-run admission control for the orchestrator (E11-S3, ADR-019).

Proves the Agent Runtime's fail-closed enforcement: a tenant at its
concurrent-run ceiling is denied *before* a run record is created, and a
granted lease is always released -- on success or on failure -- leaving no
orphaned slot behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import DurableStore, reset_store_cache
from backend.quotas.contracts import (
    QuotaExceededError,
    RunBudgetLimits,
    TenantQuotaPolicy,
)
from backend.quotas.service import QuotaService
from backend.quotas.store import QuotaStore

_TENANT_ID = "tenant-quota-test"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "autodev-quota-test.db"


@pytest.fixture()
def orchestrator_service(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[OrchestratorService]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_store_cache()
    quota_service = QuotaService(store=QuotaStore(db_path))
    quota_service.set_policy(
        TenantQuotaPolicy(
            tenant_id=_TENANT_ID,
            max_concurrent_runs=1,
            max_storage_bytes=10_000_000,
            monthly_token_limit=1_000_000,
            monthly_cost_microusd=1_000_000,
            requests_per_second=10,
            default_run_budget=RunBudgetLimits(),
        )
    )
    service = OrchestratorService(store=DurableStore(f"sqlite:///{db_path}"), quota_service=quota_service)
    yield service
    reset_store_cache()


def _create_session(service: OrchestratorService) -> str:
    return service.create_plan("Ship the quota story", tenant_id=_TENANT_ID).session_id


def test_run_denied_at_the_concurrency_ceiling_leaves_no_run_record(
    orchestrator_service: OrchestratorService,
) -> None:
    session_id = _create_session(orchestrator_service)
    quota_service = orchestrator_service._quota_service
    held_run_id = "already-running"
    lease = quota_service.acquire_run_lease(tenant_id=_TENANT_ID, run_id=held_run_id)
    assert lease.granted

    with pytest.raises(QuotaExceededError):
        orchestrator_service.handle_message(session_id, "start", tenant_id=_TENANT_ID)

    runs = orchestrator_service.list_runs(session_id, tenant_id=_TENANT_ID)
    assert runs == []

    quota_service.release_run_lease(held_run_id)


def test_lease_is_released_after_a_successful_run(orchestrator_service: OrchestratorService) -> None:
    session_id = _create_session(orchestrator_service)

    first = orchestrator_service.handle_message(session_id, "start", tenant_id=_TENANT_ID)
    assert first.status == "completed"

    # The ceiling is 1: if the first run's lease weren't released, this
    # second run would be denied.
    second = orchestrator_service.handle_message(session_id, "continue", tenant_id=_TENANT_ID)
    assert second.status == "completed"


def test_lease_is_released_after_a_failed_run(orchestrator_service: OrchestratorService) -> None:
    session_id = _create_session(orchestrator_service)
    original = orchestrator_service._execute_message_run

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("simulated agent pipeline failure")

    orchestrator_service._execute_message_run = _boom  # type: ignore[method-assign,assignment]
    try:
        with pytest.raises(RuntimeError):
            orchestrator_service.handle_message(session_id, "start", tenant_id=_TENANT_ID)
    finally:
        orchestrator_service._execute_message_run = original  # type: ignore[method-assign,assignment]

    recovered = orchestrator_service.handle_message(session_id, "retry", tenant_id=_TENANT_ID)
    assert recovered.status == "completed"
