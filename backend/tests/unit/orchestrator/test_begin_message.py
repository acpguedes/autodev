"""Tests for E43-S6: asynchronous turn creation.

``begin_message`` returns as soon as the run is admitted and persisted --
before the agent graph runs -- so a caller has a ``run_id`` to open a live
event-stream subscription against while the run is still in progress. The
graph itself then runs in the background job queue
(``backend.jobs.queue``), registered by the same module
(``backend/orchestrator/service.py``) that enqueues it.

Mirrors ``backend/tests/unit/orchestrator/test_orchestrator_quotas.py``'s
fixture (a real ``OrchestratorService`` over an isolated SQLite file), and
additionally sets ``DATABASE_URL`` so the background job's freshly-built
``build_default_orchestrator()`` instance shares the same store/quota
backing as the test's own service instance.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

import pytest

from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.jobs.queue import _reset_queue_singleton
from backend.llm.factory import get_chat_model
from backend.orchestrator.service import OrchestratorService, OrchestratorRun, RunStatus, RunSummary
from backend.persistence.database import DurableStore, reset_store_cache
from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy
from backend.quotas.service import QuotaService
from backend.quotas.store import QuotaStore

_TENANT_ID = "tenant-begin-message-test"
_POLL_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.05


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "autodev-begin-message-test.db"


@pytest.fixture()
def orchestrator_service(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[OrchestratorService]:
    """A real ``OrchestratorService`` whose store/quota state is also
    reachable via ``DATABASE_URL`` -- what the background job's own
    ``build_default_orchestrator()`` (a fresh instance) resolves through.

    Also isolates the LLM provider/config path the same way
    ``test_chat_timeline_v2.py``'s fixture does: without this,
    ``build_default_orchestrator()`` would resolve this *repository's own*
    (real) ``autodev.config.json`` -- picking a real LLM provider instead of
    the deterministic stub, and turning the background job into a real,
    slow, network-dependent API call.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    get_chat_model.cache_clear()
    # Fresh job queue (own thread pool) per test: begin_message's background
    # job reads env vars at *execution* time, not enqueue time, so a job left
    # over from a previous test's queue could otherwise run against this
    # test's monkeypatched env after it's been torn down, or vice versa.
    _reset_queue_singleton()
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
    reset_runtime_config_cache()
    get_chat_model.cache_clear()
    _reset_queue_singleton()


def _create_session(service: OrchestratorService) -> str:
    return service.create_plan("Ship the async turn story", tenant_id=_TENANT_ID).session_id


def _poll_run_until_terminal(service: OrchestratorService, session_id: str, run_id: str) -> RunSummary:
    """Poll the stored run row until its status is no longer ``running``."""
    deadline = time.monotonic() + _POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        runs = service.list_runs(session_id, tenant_id=_TENANT_ID)
        matching = next((run for run in runs if run.run_id == run_id), None)
        if matching is not None and matching.status != RunStatus.RUNNING:
            return matching
        time.sleep(_POLL_INTERVAL_S)
    raise AssertionError(f"run {run_id!r} did not reach a terminal status within {_POLL_TIMEOUT_S}s")


def test_begin_message_returns_immediately_with_a_running_run(
    orchestrator_service: OrchestratorService,
) -> None:
    """The call returns before the graph runs: running status, empty results/steps."""
    session_id = _create_session(orchestrator_service)

    run = orchestrator_service.begin_message(session_id, "start", tenant_id=_TENANT_ID)

    assert isinstance(run, OrchestratorRun)
    assert run.status == RunStatus.RUNNING
    assert run.session_id == session_id
    assert run.history == []
    assert run.results == []
    assert run.steps == []

    # The row is already durably persisted -- not just returned in memory.
    persisted = orchestrator_service.list_runs(session_id, tenant_id=_TENANT_ID)
    assert any(entry.run_id == run.run_id and entry.status == RunStatus.RUNNING for entry in persisted)

    # Drain the background job before the test (and its fixture teardown,
    # which reverts this test's monkeypatched env vars) returns -- otherwise
    # its still-running thread reads os.environ at whatever later moment it
    # actually executes, which can race a *subsequent* test's own
    # monkeypatched env vars via the process-wide runtime-config cache.
    _poll_run_until_terminal(orchestrator_service, session_id, run.run_id)


def test_begin_message_unknown_session_raises_synchronously(
    orchestrator_service: OrchestratorService,
) -> None:
    with pytest.raises(KeyError):
        orchestrator_service.begin_message("no-such-session", "start", tenant_id=_TENANT_ID)


def test_begin_message_at_the_concurrency_ceiling_leaves_no_run_record(
    orchestrator_service: OrchestratorService,
) -> None:
    """Quota admission still happens synchronously -- before any background job exists."""
    from backend.quotas.contracts import QuotaExceededError

    session_id = _create_session(orchestrator_service)
    quota_service = orchestrator_service._quota_service
    held_run_id = "already-running"
    lease = quota_service.acquire_run_lease(tenant_id=_TENANT_ID, run_id=held_run_id)
    assert lease.granted

    with pytest.raises(QuotaExceededError):
        orchestrator_service.begin_message(session_id, "start", tenant_id=_TENANT_ID)

    assert orchestrator_service.list_runs(session_id, tenant_id=_TENANT_ID) == []
    quota_service.release_run_lease(held_run_id)


def test_begin_message_eventually_completes_via_the_real_background_job(
    orchestrator_service: OrchestratorService,
) -> None:
    """End-to-end: the background job actually runs the graph and persists a
    completed run with real results, and releases the lease so a second run
    can proceed (mirrors test_orchestrator_quotas.py's synchronous coverage,
    for the async path)."""
    session_id = _create_session(orchestrator_service)

    run = orchestrator_service.begin_message(session_id, "start", tenant_id=_TENANT_ID)
    completed = _poll_run_until_terminal(orchestrator_service, session_id, run.run_id)

    assert completed.status == RunStatus.COMPLETED
    assert len(completed.results) > 0
    assert len(completed.steps) > 0

    # The ceiling is 1: if the first run's lease weren't released by the
    # background job, this second run would be denied.
    second = orchestrator_service.begin_message(session_id, "continue", tenant_id=_TENANT_ID)
    assert second.status == RunStatus.RUNNING
    _poll_run_until_terminal(orchestrator_service, session_id, second.run_id)


def test_failed_background_job_marks_the_run_failed_and_releases_the_lease(
    orchestrator_service: OrchestratorService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A graph failure inside the background job must not leave the run
    stuck at "running" forever, nor leak its concurrency lease -- the
    pre-existing gap in the synchronous path (no RunStatus.FAILED, no
    `except` around the graph invoke) that would otherwise become silent
    once there is no HTTP caller left to see a 500."""

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("simulated agent pipeline failure")

    # Class-level patch: the background job builds its own fresh
    # OrchestratorService via build_default_orchestrator(), a different
    # Python object than the fixture instance below.
    monkeypatch.setattr(OrchestratorService, "_execute_message_run", lambda self, **kwargs: _boom(**kwargs))

    session_id = _create_session(orchestrator_service)
    run = orchestrator_service.begin_message(session_id, "start", tenant_id=_TENANT_ID)
    failed = _poll_run_until_terminal(orchestrator_service, session_id, run.run_id)

    assert failed.status == RunStatus.FAILED
    assert any("simulated agent pipeline failure" in result.content for result in failed.results)

    monkeypatch.undo()
    # The ceiling is 1: if the failed run's lease weren't released, this
    # recovery run would be denied.
    recovered = orchestrator_service.begin_message(session_id, "retry", tenant_id=_TENANT_ID)
    assert recovered.status == RunStatus.RUNNING
    completed = _poll_run_until_terminal(orchestrator_service, session_id, recovered.run_id)
    assert completed.status == RunStatus.COMPLETED
