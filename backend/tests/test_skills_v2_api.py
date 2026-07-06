"""Tests for the /v2/skills catalog API (E6-S2)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.routers.skills_v2 import get_skill_registry
from backend.persistence.database import DurableStore
from backend.skills.manifest import validate_manifest
from backend.skills.registry_v2 import SkillRegistry


def _register_sample_skill(registry: SkillRegistry) -> None:
    raw = {
        "schemaVersion": "1",
        "id": "autodev/skill-run-tests",
        "version": "1.0.0",
        "hostApi": ">=2.0,<3.0",
        "kind": "deterministic",
        "entrypoint": "autodev_skills.testing:run_tests",
        "io": {
            "input": {"schemaVersion": "1", "type": "object", "required": [], "properties": {}},
            "output": {"schemaVersion": "1", "type": "object", "required": [], "properties": {}},
        },
        "permissions": {"filesystem": "read", "network": "none", "sandbox": True},
        "triggers": ["code.after-edit"],
    }
    result = validate_manifest(raw)
    assert result.valid, result.errors
    registry.register(result.manifest, plugin_id="autodev/plugin")


def test_catalog_endpoint_lists_registered_skills(tmp_path: Path) -> None:
    registry = SkillRegistry(DurableStore(f"sqlite:///{tmp_path / 'skills.db'}"))
    _register_sample_skill(registry)
    app.dependency_overrides[get_skill_registry] = lambda: registry
    try:
        response = TestClient(app).get("/v2/skills")
    finally:
        app.dependency_overrides.pop(get_skill_registry, None)

    assert response.status_code == 200
    body = response.json()
    assert body["skills"][0]["id"] == "autodev/skill-run-tests"


def test_search_endpoint_filters_by_trigger(tmp_path: Path) -> None:
    registry = SkillRegistry(DurableStore(f"sqlite:///{tmp_path / 'skills.db'}"))
    _register_sample_skill(registry)
    app.dependency_overrides[get_skill_registry] = lambda: registry
    try:
        found = TestClient(app).get("/v2/skills/search?trigger=code.after-edit")
        missing = TestClient(app).get("/v2/skills/search?trigger=flow.validation")
    finally:
        app.dependency_overrides.pop(get_skill_registry, None)

    assert len(found.json()["skills"]) == 1
    assert missing.json()["skills"] == []


def test_get_skill_resolves_version(tmp_path: Path) -> None:
    registry = SkillRegistry(DurableStore(f"sqlite:///{tmp_path / 'skills.db'}"))
    _register_sample_skill(registry)
    app.dependency_overrides[get_skill_registry] = lambda: registry
    try:
        response = TestClient(app).get("/v2/skills/autodev/skill-run-tests")
    finally:
        app.dependency_overrides.pop(get_skill_registry, None)

    assert response.status_code == 200
    assert response.json()["version"] == "1.0.0"


def test_get_skill_returns_404_when_unresolved(tmp_path: Path) -> None:
    registry = SkillRegistry(DurableStore(f"sqlite:///{tmp_path / 'skills.db'}"))
    app.dependency_overrides[get_skill_registry] = lambda: registry
    try:
        response = TestClient(app).get("/v2/skills/autodev/does-not-exist")
    finally:
        app.dependency_overrides.pop(get_skill_registry, None)

    assert response.status_code == 404
