from __future__ import annotations

import time

import pytest

from backend.plugins.catalog import EXTENSION_POINT_KINDS, ExtensionPointKind, get_extension_point
from backend.plugins.manifest import PluginManifest, load_manifest, validate_manifest


def _valid_manifest() -> dict[str, object]:
    return {
        "schemaVersion": "1",
        "id": "acme/coder-plus",
        "version": "1.2.3",
        "hostApi": ">=2.0 <3.0",
        "runtime": {
            "loader": "in-process",
            "entrypoint": "coder_plus:register",
        },
        "permissions": {
            "filesystem": {
                "read": ["${workspace}/src"],
                "write": ["${workspace}/.autodev/cache"],
            },
            "network": {"egress": ["api.example.com:443"]},
            "exec": {"commands": ["pytest"]},
            "secrets": [{"name": "EXAMPLE_TOKEN", "required": True}],
        },
        "extensionPoints": [
            {
                "kind": "agent",
                "id": "acme/coder-plus.agent",
                "contract": "^1.0",
                "entrypoint": "coder_plus.agent:CoderAgent",
            }
        ],
    }


def test_extension_catalog_contains_canonical_kinds() -> None:
    assert set(EXTENSION_POINT_KINDS) == {
        "agent",
        "skill",
        "tool",
        "reasoning",
        "router",
        "selector",
        "evaluator",
        "context_provider",
        "retriever",
        "validation_gate",
        "ui_panel",
        "event_handler",
    }
    assert get_extension_point(ExtensionPointKind.AGENT).host_subsystem == (
        "Agent Runtime + Agent Registry"
    )


def test_valid_manifest_is_accepted() -> None:
    result = validate_manifest(_valid_manifest())

    assert result.valid is True
    assert result.errors == []
    assert isinstance(result.manifest, PluginManifest)
    assert result.manifest.id == "acme/coder-plus"
    assert result.manifest.extension_points[0].kind is ExtensionPointKind.AGENT


def test_invalid_manifest_reports_actionable_reasons() -> None:
    raw = _valid_manifest()
    raw["id"] = "Bad Namespace/Coder"
    raw["version"] = "latest"
    raw["hostApi"] = "2.x"

    result = validate_manifest(raw)

    assert result.valid is False
    assert result.manifest is None
    assert "id must use namespace/name kebab-case format" in result.errors
    assert "version must be SemVer MAJOR.MINOR.PATCH" in result.errors
    assert "hostApi must be a supported range expression" in result.errors


def test_unknown_extension_point_is_rejected() -> None:
    raw = _valid_manifest()
    raw["extensionPoints"] = [
        {
            "kind": "made_up_kind",
            "id": "acme/coder-plus.fake",
            "contract": "^1.0",
            "entrypoint": "fake:register",
        }
    ]

    result = validate_manifest(raw)

    assert result.valid is False
    assert "unknown extension point kind 'made_up_kind'" in result.errors


def test_manifest_validation_stays_under_50ms() -> None:
    start = time.perf_counter()

    for _ in range(100):
        result = validate_manifest(_valid_manifest())
        assert result.valid

    average_ms = ((time.perf_counter() - start) / 100) * 1000
    assert average_ms < 50


def test_load_manifest_reads_plugin_yaml(tmp_path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """
schemaVersion: "1"
id: "acme/example-plugin"
version: "0.1.0"
hostApi: ">=2.0 <3.0"
runtime:
  loader: "in-process"
  entrypoint: "example_plugin:register"
permissions: {}
extensionPoints:
  - kind: "skill"
    id: "acme/example-plugin.skill"
    contract: "^1.0"
    entrypoint: "example_plugin.skills:ExampleSkill"
""".strip(),
        encoding="utf-8",
    )

    manifest = load_manifest(plugin_dir / "plugin.yaml")

    assert manifest.id == "acme/example-plugin"
    assert manifest.extension_points[0].kind is ExtensionPointKind.SKILL


def test_load_manifest_raises_with_reasons_for_invalid_yaml(tmp_path) -> None:
    manifest_path = tmp_path / "plugin.yaml"
    manifest_path.write_text("id: nope\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_manifest(manifest_path)

    assert "schemaVersion is required" in str(exc.value)
