"""Tests for U3 — Skills API endpoints.

Uses FastAPI's TestClient against the main app so the auto-loader wires
``backend.api.routers.skills`` transparently (no imports of the router
module directly).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    from backend.api.main import app  # noqa: PLC0415
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /skills — list
# ---------------------------------------------------------------------------


def test_list_skills_returns_200(client: TestClient) -> None:
    resp = client.get("/skills")
    assert resp.status_code == 200


def test_list_skills_is_list(client: TestClient) -> None:
    resp = client.get("/skills")
    data = resp.json()
    assert isinstance(data, list)


def test_list_skills_contains_three_builtins(client: TestClient) -> None:
    resp = client.get("/skills")
    names = {item["name"] for item in resp.json()}
    assert "summarize_diff" in names
    assert "extract_symbols_lexical" in names
    assert "render_checklist" in names


def test_list_skills_items_have_name_and_description(client: TestClient) -> None:
    resp = client.get("/skills")
    for item in resp.json():
        assert "name" in item
        assert "description" in item


# ---------------------------------------------------------------------------
# GET /skills/{name} — describe
# ---------------------------------------------------------------------------


def test_describe_known_skill_returns_200(client: TestClient) -> None:
    resp = client.get("/skills/summarize_diff")
    assert resp.status_code == 200


def test_describe_known_skill_returns_name(client: TestClient) -> None:
    resp = client.get("/skills/summarize_diff")
    assert resp.json()["name"] == "summarize_diff"


def test_describe_unknown_skill_returns_404(client: TestClient) -> None:
    resp = client.get("/skills/no_such_skill_xyz")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /skills/{name}/invoke — invoke
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,5 @@
 line
+added_one
+added_two
-removed
"""


def test_invoke_summarize_diff_returns_200(client: TestClient) -> None:
    resp = client.post(
        "/skills/summarize_diff/invoke",
        json={"inputs": {"diff": SAMPLE_DIFF}},
    )
    assert resp.status_code == 200


def test_invoke_summarize_diff_counts_correct(client: TestClient) -> None:
    resp = client.post(
        "/skills/summarize_diff/invoke",
        json={"inputs": {"diff": SAMPLE_DIFF}},
    )
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["added_lines"] == 2
    assert body["data"]["removed_lines"] == 1


def test_invoke_summarize_diff_content_is_string(client: TestClient) -> None:
    resp = client.post(
        "/skills/summarize_diff/invoke",
        json={"inputs": {"diff": SAMPLE_DIFF}},
    )
    assert isinstance(resp.json()["content"], str)


def test_invoke_unknown_skill_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/skills/no_such_skill_xyz/invoke",
        json={"inputs": {}},
    )
    assert resp.status_code == 404


def test_invoke_empty_inputs_accepted(client: TestClient) -> None:
    """render_checklist accepts empty inputs gracefully."""
    resp = client.post(
        "/skills/render_checklist/invoke",
        json={"inputs": {}},
    )
    # Should not crash — result may be empty checklist
    assert resp.status_code == 200
    assert resp.json()["success"] is True
