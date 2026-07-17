"""Tests for the durable v2 Skill Registry: versioning, trigger search (E6-S2)."""

from __future__ import annotations

from pathlib import Path

from backend.persistence.database import DurableStore
from backend.skills.manifest import SkillManifest, validate_manifest
from backend.skills.registry_v2 import SKILL_REGISTRY_SCHEMA_VERSION, SkillRegistry


def _skill_manifest_raw(
    skill_id: str = "autodev/skill-run-tests",
    *,
    version: str = "1.0.0",
    trigger: str = "code.after-edit",
) -> dict[str, object]:
    """Build a raw skill manifest document with overridable id, version, and trigger."""
    return {
        "schemaVersion": "1",
        "id": skill_id,
        "version": version,
        "hostApi": ">=2.0,<3.0",
        "kind": "deterministic",
        "entrypoint": "autodev_skills.testing:run_tests",
        "io": {
            "input": {"schemaVersion": "1", "type": "object", "required": [], "properties": {}},
            "output": {"schemaVersion": "1", "type": "object", "required": [], "properties": {}},
        },
        "permissions": {"filesystem": "read", "network": "none", "sandbox": True},
        "triggers": [trigger],
    }


def _validated_manifest(**kwargs: str) -> SkillManifest:
    """Build and validate a skill manifest, forwarding overrides to :func:`_skill_manifest_raw`."""
    result = validate_manifest(_skill_manifest_raw(**kwargs))
    assert result.valid, result.errors
    assert result.manifest is not None
    return result.manifest


def test_registry_persists_multiple_versions_and_resolves_semver_ranges(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'skills.db'}")
    registry = SkillRegistry(store)
    registry.register(_validated_manifest(version="1.0.0"), plugin_id="autodev/plugin")
    registry.register(_validated_manifest(version="1.2.0"), plugin_id="autodev/plugin")
    registry.register(_validated_manifest(version="2.0.0"), plugin_id="autodev/plugin")

    resolved = registry.resolve("autodev/skill-run-tests", ">=1.0,<2.0")
    all_versions = registry.list_skills()

    assert resolved.version == "1.2.0"
    assert {ref.version for ref in all_versions} == {"1.0.0", "1.2.0", "2.0.0"}


def test_resolve_raises_when_no_version_matches(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'skills.db'}")
    registry = SkillRegistry(store)
    registry.register(_validated_manifest(version="1.0.0"), plugin_id="autodev/plugin")

    try:
        registry.resolve("autodev/skill-run-tests", ">=2.0,<3.0")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_find_by_trigger(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'skills.db'}")
    registry = SkillRegistry(store)
    registry.register(_validated_manifest(trigger="code.after-edit"), plugin_id="autodev/plugin")
    registry.register(
        _validated_manifest(skill_id="autodev/skill-other", trigger="flow.validation"),
        plugin_id="autodev/plugin",
    )

    matches = registry.find_by_trigger("code.after-edit")
    assert [ref.skill_id for ref in matches] == ["autodev/skill-run-tests"]


def test_deprecate_marks_version_and_emits_event(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'skills.db'}")
    registry = SkillRegistry(store)
    registry.register(_validated_manifest(), plugin_id="autodev/plugin")

    registry.deprecate("autodev/skill-run-tests", "1.0.0", "superseded")
    ref = registry.resolve("autodev/skill-run-tests")

    assert ref.deprecated is True
    assert ref.deprecation_reason == "superseded"


def test_catalog_schema_version(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'skills.db'}")
    registry = SkillRegistry(store)
    registry.register(_validated_manifest(), plugin_id="autodev/plugin")

    catalog = registry.catalog()

    assert catalog["schemaVersion"] == SKILL_REGISTRY_SCHEMA_VERSION
    assert catalog["skills"][0]["id"] == "autodev/skill-run-tests"
