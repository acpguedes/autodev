"""E5-S3 API tests: /v2/evals run + results, on an isolated temp SQLite store."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient

from backend.config.settings import reset_settings_cache
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store.

    Both the settings cache and the store cache are process-wide
    ``lru_cache``s; clearing only the store cache would leave a prior test's
    cached ``Settings.database_url`` in effect, silently pointing every
    subsequent test at the *first* test's SQLite file instead of this test's
    own ``tmp_path``.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    reset_settings_cache()
    reset_store_cache()
    from backend.api.main import app

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_store_cache()
    reset_settings_cache()


def _offline_spec(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid offline eval.yaml document used across API tests."""
    spec: dict[str, Any] = {
        "schemaVersion": "1.0",
        "id": "autodev/eval-api-test",
        "version": "1.0.0",
        "target": {"kind": "agent", "agent_id": "autodev/agent-coder"},
        "mode": "offline",
        "dataset": {"ref": "autodev/golden@2026-06", "split": "test", "size": 1},
        "evaluators": [
            {"kind": "deterministic", "id": "patch_applies", "check": "patch.dry_run.ok == true"},
        ],
        "metrics": {"quality": {"primary": "patch_applies"}},
    }
    spec.update(overrides)
    return spec


def test_run_offline_eval_returns_201_and_result(client: TestClient) -> None:
    """POST /v2/evals/run executes an offline spec and returns the persisted result."""
    response = client.post(
        "/v2/evals/run",
        json={
            "spec": _offline_spec(),
            "cases": [{"caseId": "c1", "payload": {"patch": {"dry_run": {"ok": True}}}}],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["evalId"] == "autodev/eval-api-test"
    assert body["evaluators"][0]["meanScore"] == 1.0
    assert body["gate"]["passed"] is True


def test_run_eval_rejects_invalid_spec(client: TestClient) -> None:
    """POST /v2/evals/run returns 422 with error details for an invalid spec."""
    response = client.post("/v2/evals/run", json={"spec": {"id": "bad id"}, "cases": []})
    assert response.status_code == 422
    assert "errors" in response.json()["detail"]


def test_run_eval_rejects_missing_cases_for_offline(client: TestClient) -> None:
    """POST /v2/evals/run returns 422 when 'cases' is missing for an offline spec."""
    response = client.post("/v2/evals/run", json={"spec": _offline_spec()})
    assert response.status_code == 422


def test_run_eval_rejects_non_object_case_entry(client: TestClient) -> None:
    """A non-object entry in 'cases' is rejected with 422, not an unhandled 500."""
    response = client.post(
        "/v2/evals/run", json={"spec": _offline_spec(), "cases": ["not-an-object"]}
    )
    assert response.status_code == 422


def test_run_eval_rejects_non_object_case_payload(client: TestClient) -> None:
    """A malformed (non-object) 'payload' field is rejected with 422, not an unhandled 500.

    Regression test: `dict(payload)` on a list like ["a", "b"] raises ValueError
    (not AttributeError), which previously escaped the handler as a bare 500.
    """
    response = client.post(
        "/v2/evals/run",
        json={"spec": _offline_spec(), "cases": [{"caseId": "c1", "payload": ["a", "b"]}]},
    )
    assert response.status_code == 422
    assert "payload" in response.json()["detail"]


def test_run_eval_rejects_duplicate_run_id_with_409(client: TestClient) -> None:
    """Reusing a runId for the same eval id+version returns 409, not an unhandled 500.

    Regression test: the store's UNIQUE(eval_id, eval_version, run_id)
    constraint previously raised a bare sqlite3.IntegrityError that the
    handler had no way to catch, escaping as an unhandled 500.
    """
    body = {
        "spec": _offline_spec(),
        "cases": [{"caseId": "c1", "payload": {"patch": {"dry_run": {"ok": True}}}}],
        "runId": "fixed-run-id",
    }
    first = client.post("/v2/evals/run", json=body)
    assert first.status_code == 201

    second = client.post("/v2/evals/run", json=body)
    assert second.status_code == 409


def test_run_online_spec_registers_stub_without_cases(client: TestClient) -> None:
    """An online spec is registered without requiring 'cases'."""
    response = client.post(
        "/v2/evals/run",
        json={
            "spec": _offline_spec(
                mode="online",
                online={"publish_scores": True, "ab_test": None},
            )
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["mode"] == "online"
    assert body["online"]["publishScores"] is True


def test_list_and_get_results_round_trip(client: TestClient) -> None:
    """Results persisted by a run are retrievable via list and get endpoints."""
    run_response = client.post(
        "/v2/evals/run",
        json={
            "spec": _offline_spec(),
            "cases": [{"caseId": "c1", "payload": {"patch": {"dry_run": {"ok": True}}}}],
        },
    )
    run_id = run_response.json()["runId"]

    list_response = client.get("/v2/evals/results/autodev/eval-api-test")
    assert list_response.status_code == 200
    assert len(list_response.json()["results"]) == 1

    get_response = client.get(f"/v2/evals/results/autodev/eval-api-test/1.0.0/{run_id}")
    assert get_response.status_code == 200
    assert get_response.json()["runId"] == run_id


def test_get_unknown_result_returns_404(client: TestClient) -> None:
    """Fetching a non-existent result returns 404."""
    response = client.get("/v2/evals/results/autodev/does-not-exist/1.0.0/no-such-run")
    assert response.status_code == 404
