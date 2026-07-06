"""Tests for skill.yaml parsing and validation (E6-S1)."""

from __future__ import annotations

import time
from pathlib import Path

from backend.skills.manifest import load_manifest, validate_io, validate_manifest

VALID_RAW = {
    "schemaVersion": "1",
    "id": "autodev/skill-run-tests",
    "version": "1.2.0",
    "name": "Run Tests",
    "description": "Runs the project's test suite.",
    "hostApi": ">=2.0,<3.0",
    "kind": "deterministic",
    "entrypoint": "autodev_skills.testing:run_tests",
    "io": {
        "input": {
            "schemaVersion": "1",
            "type": "object",
            "required": ["repoRef"],
            "properties": {
                "repoRef": {"type": "string"},
                "command": {"type": "string"},
            },
        },
        "output": {
            "schemaVersion": "1",
            "type": "object",
            "required": ["testsPassed", "report"],
            "properties": {
                "testsPassed": {"type": "boolean"},
                "report": {"type": "string"},
            },
        },
    },
    "permissions": {"filesystem": "read", "network": "none", "sandbox": True},
    "dependencies": [{"id": "autodev/skill-checkout", "version": ">=1.0,<2.0"}],
    "triggers": ["code.after-edit", "flow.validation"],
    "budgets": {"timeoutSec": 300, "maxCostUsd": 0.10},
}


def test_valid_manifest_parses() -> None:
    result = validate_manifest(VALID_RAW)
    assert result.valid, result.errors
    manifest = result.manifest
    assert manifest is not None
    assert manifest.id == "autodev/skill-run-tests"
    assert manifest.kind == "deterministic"
    assert manifest.permissions.filesystem == "read"
    assert manifest.permissions.sandbox is True
    assert manifest.dependencies[0].id == "autodev/skill-checkout"
    assert manifest.budgets.max_cost_usd == 0.10


def test_missing_required_field_rejected() -> None:
    raw = dict(VALID_RAW)
    del raw["entrypoint"]
    result = validate_manifest(raw)
    assert not result.valid
    assert any("entrypoint" in err for err in result.errors)


def test_bad_semver_rejected() -> None:
    raw = dict(VALID_RAW)
    raw["version"] = "not-a-version"
    result = validate_manifest(raw)
    assert not result.valid
    assert any("SemVer" in err for err in result.errors)


def test_bad_kind_rejected() -> None:
    raw = dict(VALID_RAW)
    raw["kind"] = "magic"
    result = validate_manifest(raw)
    assert not result.valid
    assert any("kind" in err for err in result.errors)


def test_llm_assisted_kind_distinguished() -> None:
    raw = dict(VALID_RAW)
    raw["kind"] = "llm-assisted"
    result = validate_manifest(raw)
    assert result.valid, result.errors
    assert result.manifest is not None
    assert result.manifest.kind == "llm-assisted"


def test_load_manifest_from_disk(tmp_path: Path) -> None:
    import yaml

    manifest_path = tmp_path / "skill.yaml"
    manifest_path.write_text(yaml.safe_dump(VALID_RAW), encoding="utf-8")
    manifest = load_manifest(manifest_path)
    assert manifest.id == "autodev/skill-run-tests"


def test_validate_io_accepts_declared_shape() -> None:
    result = validate_manifest(VALID_RAW)
    assert result.manifest is not None
    errors = validate_io(result.manifest.io_input, {"repoRef": "abc", "command": "pytest -q"})
    assert errors == []


def test_validate_io_rejects_undeclared_key() -> None:
    result = validate_manifest(VALID_RAW)
    assert result.manifest is not None
    errors = validate_io(result.manifest.io_input, {"repoRef": "abc", "extra": 1})
    assert any("extra" in err for err in errors)


def test_validate_io_rejects_missing_required() -> None:
    result = validate_manifest(VALID_RAW)
    assert result.manifest is not None
    errors = validate_io(result.manifest.io_input, {"command": "pytest -q"})
    assert any("repoRef" in err for err in errors)


def test_validate_io_rejects_wrong_type() -> None:
    result = validate_manifest(VALID_RAW)
    assert result.manifest is not None
    errors = validate_io(result.manifest.io_output, {"testsPassed": "yes", "report": "ok"})
    assert any("testsPassed" in err for err in errors)


def test_validate_io_is_fast() -> None:
    result = validate_manifest(VALID_RAW)
    assert result.manifest is not None
    payload = {"repoRef": "abc", "command": "pytest -q"}
    started = time.perf_counter()
    for _ in range(1000):
        validate_io(result.manifest.io_input, payload)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms / 1000 < 20
