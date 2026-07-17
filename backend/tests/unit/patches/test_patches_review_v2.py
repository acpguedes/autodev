"""E16-S3 contract tests for ``/v2/sessions/{session_id}/patches`` (patch review & apply).

Exercises the full review lifecycle on top of the E0 patch engine: changed-
file listing with +/- stats, unified diff retrieval, an edited-content
override, dry-run apply (default) vs. real apply (explicit flag), the
rejected-apply-outside-guarded-path case, discard, audit-trail presence, and
``schemaVersion`` on every response.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config.runtime import reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.events.runtime import reset_event_bus_for_tests
from backend.llm.factory import get_chat_model
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store, with the patch workspace pinned to ``tmp_path``.

    Mirrors ``backend/tests/test_v2_api_contract.py``'s isolation fixture,
    plus resets the patch review router's in-process store and the event
    bus, and overrides ``get_patch_workspace_root`` so a real apply can never
    write outside the test's temp directory.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'v2-patches.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    reset_event_bus_for_tests()
    get_chat_model.cache_clear()

    from backend.api.main import app
    from backend.api.routers.patches_review_v2 import get_patch_workspace_root, reset_patch_review_store_for_tests

    reset_patch_review_store_for_tests()
    app.dependency_overrides[get_patch_workspace_root] = lambda: tmp_path

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    reset_patch_review_store_for_tests()
    reset_store_cache()
    reset_runtime_config_cache()
    reset_event_bus_for_tests()
    get_chat_model.cache_clear()


SESSION_ID = "sess-e16-s3"


def _propose(client: TestClient, path: str = "app/greeting.py", original: str = "line1\nline2\n", updated: str = "line1\nline2\nline3\n") -> dict:
    """Helper: POST a candidate patch and return the parsed response body."""
    response = client.post(f"/v2/sessions/{SESSION_ID}/patches", json={"path": path, "original": original, "updated": updated})
    assert response.status_code == 201, response.text
    return response.json()


class TestProposeAndListChangedFiles:
    """Propose endpoint and the changed-file list with +/- stats."""

    def test_propose_happy_path(self, client: TestClient) -> None:
        body = _propose(client)
        assert body["schemaVersion"] == "2.0"
        assert body["patch_id"]
        assert body["status"] == "proposed"
        assert body["path"] == "app/greeting.py"
        assert "+line3" in body["diff"]
        assert body["added_lines"] == 1
        assert body["removed_lines"] == 0
        assert len(body["audit"]) == 1
        assert body["audit"][0]["action"] == "propose"
        assert body["audit"][0]["actor"]
        assert body["audit"][0]["timestamp"]

    def test_list_changed_files_with_stats(self, client: TestClient) -> None:
        _propose(client, path="a.py", original="x\n", updated="x\ny\nz\n")
        _propose(client, path="b.py", original="1\n2\n", updated="1\n")
        response = client.get(f"/v2/sessions/{SESSION_ID}/patches")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["session_id"] == SESSION_ID
        assert body["page"] == {"limit": 20, "offset": 0, "total": 2}
        by_path = {item["path"]: item for item in body["items"]}
        assert by_path["a.py"]["added_lines"] == 2
        assert by_path["a.py"]["removed_lines"] == 0
        assert by_path["b.py"]["added_lines"] == 0
        assert by_path["b.py"]["removed_lines"] == 1
        for item in body["items"]:
            assert item["schemaVersion"] == "2.0"
            assert item["status"] == "proposed"

    def test_list_changed_files_paginated(self, client: TestClient) -> None:
        _propose(client, path="a.py")
        _propose(client, path="b.py")
        response = client.get(f"/v2/sessions/{SESSION_ID}/patches", params={"limit": 1, "offset": 0})
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        assert body["page"] == {"limit": 1, "offset": 0, "total": 2}

    def test_list_changed_files_empty_session_is_empty(self, client: TestClient) -> None:
        response = client.get("/v2/sessions/no-such-session/patches")
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["page"]["total"] == 0


class TestPatchDetailAndDiff:
    """Unified diff retrieval per changed file."""

    def test_get_patch_diff_happy_path(self, client: TestClient) -> None:
        created = _propose(client)
        response = client.get(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["diff"] == created["diff"]
        assert "--- a/app/greeting.py" in body["diff"]
        assert "+++ b/app/greeting.py" in body["diff"]

    def test_get_patch_diff_unknown_returns_standard_error_envelope(self, client: TestClient) -> None:
        response = client.get(f"/v2/sessions/{SESSION_ID}/patches/no-such-patch")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["schemaVersion"] == "2.0"
        assert detail["error"]["code"] == 404


class TestOverrideContent:
    """Edited-content override endpoint."""

    def test_override_updates_diff_and_keeps_status_proposed(self, client: TestClient) -> None:
        created = _propose(client, original="line1\n", updated="line1\nline2\n")
        response = client.put(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}/content", json={"updated": "line1\nedited\n"})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["status"] == "proposed"
        assert body["updated"] == "line1\nedited\n"
        assert "+edited" in body["diff"]
        assert any(entry["action"] == "override" for entry in body["audit"])

    def test_override_unknown_patch_returns_404(self, client: TestClient) -> None:
        response = client.put(f"/v2/sessions/{SESSION_ID}/patches/no-such-patch/content", json={"updated": "x\n"})
        assert response.status_code == 404


class TestApplyDryRunVsReal:
    """Apply endpoint: dry-run by default, real apply requires an explicit flag."""

    def test_apply_defaults_to_dry_run_and_does_not_write(self, client: TestClient, tmp_path: Path) -> None:
        created = _propose(client, path="dry_run_target.py", original="a\n", updated="a\nb\n")
        response = client.post(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}/apply", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["applied"] is False
        assert body["dry_run"] is True
        assert body["audit"]["action"] == "apply"
        assert body["audit"]["result"] == "dry_run"
        assert body["audit"]["actor"]
        assert body["audit"]["timestamp"]
        assert not (tmp_path / "dry_run_target.py").exists()

        detail = client.get(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}").json()
        assert detail["status"] == "proposed"

    def test_apply_with_explicit_flag_writes_and_marks_applied(self, client: TestClient, tmp_path: Path) -> None:
        created = _propose(client, path="real_apply_target.py", original="", updated="hello\n")
        response = client.post(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}/apply", json={"apply": True})
        assert response.status_code == 200
        body = response.json()
        assert body["applied"] is True
        assert body["dry_run"] is False
        assert body["audit"]["result"] == "applied"
        written = tmp_path / "real_apply_target.py"
        assert written.exists()
        assert written.read_text(encoding="utf-8") == "hello\n"

        detail = client.get(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}").json()
        assert detail["status"] == "applied"

    def test_apply_rejects_path_traversal_outside_guarded_root(self, client: TestClient) -> None:
        created = _propose(client, path="../../etc/passwd", original="old\n", updated="evil\n")
        response = client.post(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}/apply", json={"apply": True})
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["schemaVersion"] == "2.0"
        assert detail["error"]["code"] == 400
        assert "traversal" in detail["error"]["message"].lower()

        detail_body = client.get(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}").json()
        assert detail_body["status"] == "proposed"
        assert any(entry["result"] == "denied" for entry in detail_body["audit"])

    def test_apply_on_already_applied_patch_returns_409(self, client: TestClient) -> None:
        created = _propose(client, path="twice.py", original="", updated="x\n")
        client.post(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}/apply", json={"apply": True})
        response = client.post(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}/apply", json={"apply": True})
        assert response.status_code == 409
        assert response.json()["detail"]["schemaVersion"] == "2.0"


class TestDiscard:
    """Discard endpoint."""

    def test_discard_marks_patch_discarded(self, client: TestClient) -> None:
        created = _propose(client, path="discard_me.py")
        response = client.post(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}/discard")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["status"] == "discarded"
        assert any(entry["action"] == "discard" for entry in body["audit"])

    def test_apply_after_discard_returns_409(self, client: TestClient) -> None:
        created = _propose(client, path="discard_then_apply.py")
        client.post(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}/discard")
        response = client.post(f"/v2/sessions/{SESSION_ID}/patches/{created['patch_id']}/apply", json={"apply": True})
        assert response.status_code == 409

    def test_discard_unknown_patch_returns_404(self, client: TestClient) -> None:
        response = client.post(f"/v2/sessions/{SESSION_ID}/patches/no-such-patch/discard")
        assert response.status_code == 404
