"""Tests for least-privilege skill invocation via the Agent Runtime (E6-S3)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from backend.persistence.database import DurableStore
from backend.skills.invoker import SkillBudgetExceeded, SkillInvocationBroker, SkillInvocationDenied
from backend.skills.manifest import validate_manifest
from backend.skills.registry_v2 import SkillRegistry

_MODULE_SOURCE = textwrap.dedent(
    """
    import time

    def run_ok(repoRef):
        return {"testsPassed": True, "report": f"ran {repoRef}"}

    def run_slow(repoRef):
        time.sleep(1.0)
        return {"testsPassed": True, "report": "too slow"}

    def run_bad_output(repoRef):
        return {"testsPassed": "not-a-bool", "report": "oops"}
    """
)


@pytest.fixture
def entrypoint_module(tmp_path: Path):
    """Write and import a throwaway module providing sample skill entrypoints."""
    (tmp_path / "sample_skill_mod.py").write_text(_MODULE_SOURCE, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        yield "sample_skill_mod"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("sample_skill_mod", None)


def _manifest_raw(entrypoint: str, *, timeout_sec: float = 60.0) -> dict[str, object]:
    return {
        "schemaVersion": "1",
        "id": "autodev/skill-run-tests",
        "version": "1.0.0",
        "hostApi": ">=2.0,<3.0",
        "kind": "deterministic",
        "entrypoint": entrypoint,
        "io": {
            "input": {
                "schemaVersion": "1",
                "type": "object",
                "required": ["repoRef"],
                "properties": {"repoRef": {"type": "string"}},
            },
            "output": {
                "schemaVersion": "1",
                "type": "object",
                "required": ["testsPassed", "report"],
                "properties": {"testsPassed": {"type": "boolean"}, "report": {"type": "string"}},
            },
        },
        "permissions": {"filesystem": "none", "network": "none", "sandbox": True},
        "budgets": {"timeoutSec": timeout_sec, "maxCostUsd": 0.0},
    }


def _registry(tmp_path: Path, raw: dict[str, object]) -> SkillRegistry:
    store = DurableStore(f"sqlite:///{tmp_path / 'skills.db'}")
    registry = SkillRegistry(store)
    result = validate_manifest(raw)
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="autodev/plugin")
    return registry


def test_successful_invocation_returns_validated_output(entrypoint_module: str, tmp_path: Path) -> None:
    registry = _registry(tmp_path, _manifest_raw(f"{entrypoint_module}:run_ok"))
    broker = SkillInvocationBroker(registry, workspace=tmp_path)

    result = broker.invoke("autodev/skill-run-tests", repoRef="acme/repo")

    assert result == {"testsPassed": True, "report": "ran acme/repo"}


def test_invocation_denied_when_skill_not_found(tmp_path: Path) -> None:
    store = DurableStore(f"sqlite:///{tmp_path / 'skills.db'}")
    registry = SkillRegistry(store)
    broker = SkillInvocationBroker(registry, workspace=tmp_path)

    with pytest.raises(SkillInvocationDenied):
        broker.invoke("autodev/does-not-exist", repoRef="acme/repo")


def test_invocation_denied_on_invalid_input(entrypoint_module: str, tmp_path: Path) -> None:
    registry = _registry(tmp_path, _manifest_raw(f"{entrypoint_module}:run_ok"))
    broker = SkillInvocationBroker(registry, workspace=tmp_path)

    with pytest.raises(SkillInvocationDenied):
        broker.invoke("autodev/skill-run-tests")  # missing required repoRef


def test_invocation_denied_on_invalid_output(entrypoint_module: str, tmp_path: Path) -> None:
    registry = _registry(tmp_path, _manifest_raw(f"{entrypoint_module}:run_bad_output"))
    broker = SkillInvocationBroker(registry, workspace=tmp_path)

    with pytest.raises(SkillInvocationDenied):
        broker.invoke("autodev/skill-run-tests", repoRef="acme/repo")


def test_budget_exceeded_raises(entrypoint_module: str, tmp_path: Path) -> None:
    registry = _registry(tmp_path, _manifest_raw(f"{entrypoint_module}:run_slow", timeout_sec=0.05))
    broker = SkillInvocationBroker(registry, workspace=tmp_path)

    with pytest.raises(SkillBudgetExceeded):
        broker.invoke("autodev/skill-run-tests", repoRef="acme/repo")


def test_invocation_emits_trace_events(entrypoint_module: str, tmp_path: Path) -> None:
    registry = _registry(tmp_path, _manifest_raw(f"{entrypoint_module}:run_ok"))
    events: list[str] = []
    broker = SkillInvocationBroker(registry, workspace=tmp_path, event_sink=lambda event: events.append(event.name))

    broker.invoke("autodev/skill-run-tests", repoRef="acme/repo")

    assert events == ["skill.invocation.completed"]


def test_denial_emits_trace_event(entrypoint_module: str, tmp_path: Path) -> None:
    registry = _registry(tmp_path, _manifest_raw(f"{entrypoint_module}:run_bad_output"))
    events: list[str] = []
    broker = SkillInvocationBroker(registry, workspace=tmp_path, event_sink=lambda event: events.append(event.name))

    with pytest.raises(SkillInvocationDenied):
        broker.invoke("autodev/skill-run-tests", repoRef="acme/repo")

    assert events == ["skill.invocation.denied"]
