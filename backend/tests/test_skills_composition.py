"""Tests for skill-to-skill pipeline composition (E6-S4)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from backend.persistence.database import DurableStore
from backend.skills.composition import PipelineStep, SkillCompositionError, run_pipeline
from backend.skills.invoker import SkillInvocationBroker
from backend.skills.manifest import validate_manifest
from backend.skills.registry_v2 import SkillRegistry

_MODULE_SOURCE = textwrap.dedent(
    """
    CALLS = []

    def step_a(x):
        CALLS.append("a")
        return {"y": x + "-a"}

    def step_b(y):
        CALLS.append("b")
        return {"z": y + "-b"}

    def step_b_bad_output(y):
        CALLS.append("b")
        return {"z": 123}
    """
)


@pytest.fixture
def entrypoint_module(tmp_path: Path):
    """Write and import a throwaway module providing chained sample skill steps."""
    (tmp_path / "pipeline_mod.py").write_text(_MODULE_SOURCE, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        module_name = "pipeline_mod"
        yield module_name
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("pipeline_mod", None)


def _io(required: str, prop: str) -> dict[str, object]:
    return {
        "schemaVersion": "1",
        "type": "object",
        "required": [required],
        "properties": {prop: {"type": "string"}},
    }


def _skill_raw(
    skill_id: str,
    entrypoint: str,
    *,
    input_key: str = "x",
    output_key: str = "y",
    output_type: str = "string",
    dependencies: list[dict[str, str]] | None = None,
    timeout_sec: float = 60.0,
) -> dict[str, object]:
    return {
        "schemaVersion": "1",
        "id": skill_id,
        "version": "1.0.0",
        "hostApi": ">=2.0,<3.0",
        "kind": "deterministic",
        "entrypoint": entrypoint,
        "io": {
            "input": {
                "schemaVersion": "1",
                "type": "object",
                "required": [input_key],
                "properties": {input_key: {"type": "string"}},
            },
            "output": {
                "schemaVersion": "1",
                "type": "object",
                "required": [output_key],
                "properties": {output_key: {"type": output_type}},
            },
        },
        "permissions": {"filesystem": "none", "network": "none", "sandbox": True},
        "dependencies": dependencies or [],
        "budgets": {"timeoutSec": timeout_sec, "maxCostUsd": 0.0},
    }


def _setup(tmp_path: Path):
    store = DurableStore(f"sqlite:///{tmp_path / 'skills.db'}")
    registry = SkillRegistry(store)
    invoker = SkillInvocationBroker(registry, workspace=tmp_path)
    return registry, invoker


def _register(registry: SkillRegistry, raw: dict[str, object]) -> None:
    result = validate_manifest(raw)
    assert result.valid, result.errors
    assert result.manifest is not None
    registry.register(result.manifest, plugin_id="autodev/plugin")


def test_successful_two_step_pipeline(entrypoint_module: str, tmp_path: Path) -> None:
    registry, invoker = _setup(tmp_path)
    _register(registry, _skill_raw("autodev/skill-a", f"{entrypoint_module}:step_a", input_key="x", output_key="y"))
    _register(registry, _skill_raw("autodev/skill-b", f"{entrypoint_module}:step_b", input_key="y", output_key="z"))

    result = run_pipeline(
        [PipelineStep("autodev/skill-a"), PipelineStep("autodev/skill-b")],
        {"x": "start"},
        registry=registry,
        invoker=invoker,
    )

    assert result == {"z": "start-a-b"}


def test_missing_dependency_reported_before_any_step_runs(entrypoint_module: str, tmp_path: Path) -> None:
    registry, invoker = _setup(tmp_path)
    _register(
        registry,
        _skill_raw(
            "autodev/skill-a",
            f"{entrypoint_module}:step_a",
            dependencies=[{"id": "autodev/skill-missing", "version": ">=1.0,<2.0"}],
        ),
    )

    with pytest.raises(SkillCompositionError) as exc_info:
        run_pipeline([PipelineStep("autodev/skill-a")], {"x": "start"}, registry=registry, invoker=invoker)

    assert exc_info.value.reason == "missing-dependency"

    import pipeline_mod  # type: ignore[import-not-found]

    assert pipeline_mod.CALLS == []


def test_mid_pipeline_failure_stops_execution(entrypoint_module: str, tmp_path: Path) -> None:
    registry, invoker = _setup(tmp_path)
    _register(registry, _skill_raw("autodev/skill-a", f"{entrypoint_module}:step_a", input_key="x", output_key="y"))
    _register(
        registry,
        _skill_raw(
            "autodev/skill-b",
            f"{entrypoint_module}:step_b_bad_output",
            input_key="y",
            output_key="z",
        ),
    )

    with pytest.raises(SkillCompositionError) as exc_info:
        run_pipeline(
            [PipelineStep("autodev/skill-a"), PipelineStep("autodev/skill-b")],
            {"x": "start"},
            registry=registry,
            invoker=invoker,
        )

    assert exc_info.value.step_index == 1
    assert exc_info.value.reason == "denied"

    import pipeline_mod  # type: ignore[import-not-found]

    assert pipeline_mod.CALLS == ["a", "b"]


def test_aggregated_budget_exceeded_stops_before_execution(entrypoint_module: str, tmp_path: Path) -> None:
    registry, invoker = _setup(tmp_path)
    _register(
        registry,
        _skill_raw("autodev/skill-a", f"{entrypoint_module}:step_a", input_key="x", output_key="y", timeout_sec=40),
    )
    _register(
        registry,
        _skill_raw("autodev/skill-b", f"{entrypoint_module}:step_b", input_key="y", output_key="z", timeout_sec=40),
    )

    with pytest.raises(SkillCompositionError) as exc_info:
        run_pipeline(
            [PipelineStep("autodev/skill-a"), PipelineStep("autodev/skill-b")],
            {"x": "start"},
            registry=registry,
            invoker=invoker,
            max_total_timeout_sec=60,
        )

    assert exc_info.value.reason == "aggregated-budget-exceeded"

    import pipeline_mod  # type: ignore[import-not-found]

    assert pipeline_mod.CALLS == []
