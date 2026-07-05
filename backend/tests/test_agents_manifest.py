"""Tests for agent.yaml manifest parsing, validation, and IO schema checks."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.agents.manifest import (
    DEFAULT_AGENT_BUDGETS,
    AgentManifest,
    ValidationError,
    load_agent_manifest,
    validate_agent_io,
    validate_agent_manifest,
)


def _input_schema() -> dict[str, object]:
    """Build a sample JSON Schema for agent input used across manifest tests."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "task"],
        "properties": {
            "schemaVersion": {"const": "1.0.0"},
            "task": {"type": "string", "minLength": 1},
            "context": {"type": "object", "additionalProperties": True},
        },
    }


def _output_schema() -> dict[str, object]:
    """Build a sample JSON Schema for agent output used across manifest tests."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "status", "result"],
        "properties": {
            "schemaVersion": {"const": "1.0.0"},
            "status": {"enum": ["ok", "error"]},
            "result": {"type": "string"},
        },
    }


def _valid_agent_manifest() -> dict[str, object]:
    """Build a fully valid raw agent manifest document for use as a test baseline."""
    return {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": "acme/agent-coder",
        "version": "1.2.3",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [
            {"id": "code.implementation", "version": "1.0.0", "level": "primary"},
            {"id": "code.refactor", "version": "1.0.0", "level": "secondary"},
        ],
        "io": {
            "contract": "acme/coder-io",
            "contractVersion": "1.0.0",
            "input": _input_schema(),
            "output": _output_schema(),
            "onInvalidOutput": "fail",
        },
        "permissions": {
            "tools": [{"id": "fs.read"}, {"id": "patch.apply"}],
            "skills": [{"id": "autodev/skill-unified-diff", "versionRange": ">=1.0 <2.0"}],
        },
        "entrypoint": {"runtime": "python", "ref": "acme_coder.agent:CoderAgent"},
    }


def test_valid_agent_manifest_is_typed_and_inherits_safe_budgets() -> None:
    """A valid manifest parses successfully and inherits the default safe budgets."""
    result = validate_agent_manifest(_valid_agent_manifest())

    assert result.valid is True
    assert result.errors == []
    assert isinstance(result.manifest, AgentManifest)
    assert result.manifest.id == "acme/agent-coder"
    assert result.manifest.budgets.tokens_input == DEFAULT_AGENT_BUDGETS.tokens_input
    assert result.manifest.permissions.network == "none"


def test_agent_manifest_rejects_invalid_identity_version_and_unknown_capability() -> None:
    """Validation rejects a bad id, non-SemVer version, and unknown capability together."""
    raw = _valid_agent_manifest()
    raw["id"] = "Bad/Agent"
    raw["version"] = "latest"
    raw["capabilities"] = [{"id": "magic.do-anything", "version": "1.0.0"}]

    result = validate_agent_manifest(raw)

    assert result.valid is False
    assert "id must use namespace/name kebab-case format" in result.errors
    assert "version must be SemVer MAJOR.MINOR.PATCH" in result.errors
    assert "unknown capability magic.do-anything" in result.errors


def test_agent_io_rejects_unknown_input_and_output_fields() -> None:
    """IO validation rejects payloads with properties outside the declared schema."""
    manifest = validate_agent_manifest(_valid_agent_manifest()).manifest
    assert manifest is not None

    with pytest.raises(ValidationError) as input_error:
        validate_agent_io(manifest, {"schemaVersion": "1.0.0", "task": "build", "extra": True}, "input")

    with pytest.raises(ValidationError) as output_error:
        validate_agent_io(
            manifest,
            {"schemaVersion": "1.0.0", "status": "ok", "result": "done", "extra": True},
            "output",
        )

    assert "additional property extra is not allowed" in str(input_error.value)
    assert "additional property extra is not allowed" in str(output_error.value)


def test_agent_io_validation_stays_under_20ms() -> None:
    """IO schema validation stays fast enough for the runtime's per-step budget."""
    manifest = validate_agent_manifest(_valid_agent_manifest()).manifest
    assert manifest is not None
    payload = {"schemaVersion": "1.0.0", "task": "build"}

    started = time.perf_counter()
    for _ in range(100):
        validate_agent_io(manifest, payload, "input")
    average_ms = ((time.perf_counter() - started) / 100) * 1000

    assert average_ms < 20


def test_load_agent_manifest_resolves_local_schema_refs(tmp_path: Path) -> None:
    """Loading a manifest inlines local ``$ref`` schema files under the plugin directory."""
    plugin_dir = tmp_path / "plugin"
    contracts = plugin_dir / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "input.schema.json").write_text(
        '{"type":"object","additionalProperties":false,"required":["schemaVersion"],'
        '"properties":{"schemaVersion":{"const":"1.0.0"}}}',
        encoding="utf-8",
    )
    (contracts / "output.schema.json").write_text(
        '{"type":"object","additionalProperties":false,"required":["schemaVersion"],'
        '"properties":{"schemaVersion":{"const":"1.0.0"}}}',
        encoding="utf-8",
    )
    (plugin_dir / "agent.yaml").write_text(
        """
schemaVersion: "2.0"
kind: Agent
id: "acme/ref-agent"
version: "0.1.0"
hostApi: ">=2.0 <3.0"
capabilities:
  - id: "code.implementation"
    version: "1.0.0"
io:
  contract: "acme/ref-io"
  contractVersion: "1.0.0"
  input:
    $ref: "./contracts/input.schema.json"
  output:
    $ref: "./contracts/output.schema.json"
entrypoint:
  runtime: python
  ref: "ref_agent:Agent"
""".strip(),
        encoding="utf-8",
    )

    manifest = load_agent_manifest(plugin_dir / "agent.yaml")

    assert manifest.io.input_schema["required"] == ["schemaVersion"]
    assert manifest.io.output_schema["required"] == ["schemaVersion"]
