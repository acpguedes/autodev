"""Parity suite for the E6-S5 reference skill plugins (deterministic + llm-assisted)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from backend.persistence.database import DurableStore
from backend.skills.invoker import SkillInvocationBroker
from backend.skills.manifest import load_manifest, validate_manifest
from backend.skills.registry_v2 import SkillRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
APPLY_PATCH_DIR = REPO_ROOT / "examples" / "plugins" / "skill-apply-patch"
SUMMARIZE_LLM_DIR = REPO_ROOT / "examples" / "plugins" / "skill-summarize-llm"


@pytest.fixture(autouse=True)
def _reference_plugins_on_path():
    """Make the reference plugin entrypoint modules importable for the duration of a test."""
    for plugin_dir in (APPLY_PATCH_DIR, SUMMARIZE_LLM_DIR):
        sys.path.insert(0, str(plugin_dir))
    try:
        yield
    finally:
        for plugin_dir in (APPLY_PATCH_DIR, SUMMARIZE_LLM_DIR):
            sys.path.remove(str(plugin_dir))
        sys.modules.pop("autodev_skill_apply_patch", None)
        sys.modules.pop("autodev_skill_summarize_llm", None)


def _registry_and_invoker(tmp_path: Path, workspace: Path) -> tuple[SkillRegistry, SkillInvocationBroker]:
    store = DurableStore(f"sqlite:///{tmp_path / 'skills.db'}")
    registry = SkillRegistry(store)
    invoker = SkillInvocationBroker(registry, workspace=workspace)
    return registry, invoker


@pytest.mark.parametrize(
    "plugin_dir",
    [APPLY_PATCH_DIR, SUMMARIZE_LLM_DIR],
    ids=["apply-patch", "summarize-llm"],
)
def test_plugin_and_skill_manifests_are_valid(plugin_dir: Path) -> None:
    plugin_raw = yaml.safe_load((plugin_dir / "plugin.yaml").read_text(encoding="utf-8"))
    assert plugin_raw["extensionPoints"][0]["kind"] == "skill"

    skill_manifest = load_manifest(plugin_dir / "skill.yaml")
    module_name = skill_manifest.entrypoint.split(":", 1)[0]
    assert module_name in {"autodev_skill_apply_patch", "autodev_skill_summarize_llm"}


def test_apply_patch_skill_is_dry_run_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry, invoker = _registry_and_invoker(tmp_path, workspace)
    result = validate_manifest(yaml.safe_load((APPLY_PATCH_DIR / "skill.yaml").read_text(encoding="utf-8")))
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="autodev/skill-apply-patch")

    output = invoker.invoke(
        "autodev/skill-apply-patch",
        path="hello.txt",
        original="",
        updated="hi",
        root=str(workspace),
    )

    assert output["applied"] is False
    assert output["dryRun"] is True
    assert not (workspace / "hello.txt").exists()


def test_apply_patch_skill_writes_when_enabled(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry, invoker = _registry_and_invoker(tmp_path, workspace)
    result = validate_manifest(yaml.safe_load((APPLY_PATCH_DIR / "skill.yaml").read_text(encoding="utf-8")))
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="autodev/skill-apply-patch")

    output = invoker.invoke(
        "autodev/skill-apply-patch",
        path="hello.txt",
        original="",
        updated="hi",
        root=str(workspace),
        enable=True,
    )

    assert output["applied"] is True
    assert (workspace / "hello.txt").read_text(encoding="utf-8") == "hi"


def test_summarize_llm_skill_runs_offline(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry, invoker = _registry_and_invoker(tmp_path, workspace)
    result = validate_manifest(yaml.safe_load((SUMMARIZE_LLM_DIR / "skill.yaml").read_text(encoding="utf-8")))
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="autodev/skill-summarize-llm")

    output = invoker.invoke("autodev/skill-summarize-llm", prompt="what happened?")

    assert output == {"summary": "stub summary"}
