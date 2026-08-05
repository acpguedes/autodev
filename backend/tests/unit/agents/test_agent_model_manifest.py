"""Tests for additive model configuration in agent manifests."""

from __future__ import annotations

from backend.agents.manifest import validate_agent_manifest


def _manifest(*, schema_version: str = "2.0") -> dict[str, object]:
    """Return a minimal valid v2 agent manifest."""
    return {
        "schemaVersion": schema_version,
        "kind": "Agent",
        "id": "acme/agent-coder",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": "code.implementation", "version": "1.0.0"}],
        "io": {
            "contract": "acme/coder-io",
            "contractVersion": "1.0.0",
            "input": {"type": "object"},
            "output": {"type": "object"},
        },
        "entrypoint": {"runtime": "python", "ref": "acme.agent:CoderAgent"},
    }


def test_agent_manifest_21_parses_typed_model_configuration() -> None:
    """A 2.1 manifest exposes canonical model configuration on the typed manifest."""
    raw = _manifest(schema_version="2.1")
    raw["model"] = {
        "provider": "stub",
        "name": "coder-primary",
        "temperature": 0.1,
        "maxTokens": 8000,
        "timeoutSeconds": 30,
        "retries": 1,
        "requiredCapabilities": ["text"],
        "fallbackOn": ["timeout", "rate_limit", "unavailable"],
        "limits": {"maxCalls": 4, "maxTotalTokens": 16000, "maxCostUsd": 1.0},
        "fallback": [{"provider": "stub", "name": "coder-safe"}],
    }

    result = validate_agent_manifest(raw)

    assert result.valid is True
    assert result.manifest is not None
    assert result.manifest.schema_version == "2.1"
    assert result.manifest.model is not None
    assert result.manifest.model.name == "coder-primary"


def test_agent_manifest_rejects_invalid_and_sensitive_model_configuration() -> None:
    """Model validation errors are returned through normal manifest validation."""
    raw = _manifest(schema_version="2.1")
    raw["model"] = {
        "provider": "stub",
        "name": "coder-primary",
        "temperature": 3,
        "metadata": {"clientSecret": "never-inline"},
    }

    result = validate_agent_manifest(raw)

    assert result.valid is False
    assert "model.temperature must be between 0 and 2" in result.errors
    assert "model.metadata.clientSecret is sensitive and must not be stored in manifests" in result.errors


def test_agent_manifest_20_without_model_is_unchanged() -> None:
    """Existing 2.0 manifests remain valid and have no model override."""
    result = validate_agent_manifest(_manifest())

    assert result.valid is True
    assert result.manifest is not None
    assert result.manifest.schema_version == "2.0"
    assert result.manifest.model is None


def test_legacy_policy_model_is_a_provider_inheriting_alias() -> None:
    """A legacy policy.model string becomes a typed target with inherited provider selection."""
    raw = _manifest()
    raw["policy"] = {"model": "coder-legacy", "mode": "safe"}

    result = validate_agent_manifest(raw)

    assert result.valid is True
    assert result.manifest is not None
    assert result.manifest.model is not None
    assert result.manifest.model.provider is None
    assert result.manifest.model.name == "coder-legacy"
    assert result.manifest.policy == {"model": "coder-legacy", "mode": "safe"}


def test_agent_manifest_rejects_both_model_forms() -> None:
    """A manifest cannot ambiguously declare canonical and legacy model selection."""
    raw = _manifest(schema_version="2.1")
    raw["model"] = {"provider": "stub", "name": "coder-primary"}
    raw["policy"] = {"model": "coder-legacy"}

    result = validate_agent_manifest(raw)

    assert result.valid is False
    assert "model and policy.model cannot both be declared" in result.errors
