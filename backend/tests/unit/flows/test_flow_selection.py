"""E63-S3 tests: deterministic gate, constrained choice, fail-closed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.flows.manifest import validate_flow_manifest
from backend.flows.registry import FlowRegistry
from backend.flows.selection import FlowSelector
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.projects.state import ProjectState

POPULATED = ProjectState(populated=True, git=True, tests=True, languages=("python",))
EMPTY = ProjectState()


def _flow(flow_id: str, requires: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schemaVersion": "1",
        "id": flow_id,
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "purpose": f"purpose of {flow_id}",
        "whenToUse": "when needed",
        "nodes": [{"id": "a", "type": "agent", "ref": "autodev/agent-coder"}],
        "edges": [],
    }
    if requires is not None:
        doc["requires"] = requires
    doc.update(extra)
    return doc


def _registry(tmp_path: Path, *docs: dict[str, Any]) -> FlowRegistry:
    registry = FlowRegistry(SQLiteStore(f"sqlite:///{tmp_path / 'sel.db'}"))
    for doc in docs:
        assert validate_flow_manifest(doc).valid, validate_flow_manifest(doc).errors
        registry.register_raw(doc)
    return registry


def test_gate_eliminates_bootstrap_even_if_model_chooses_it(tmp_path: Path) -> None:
    registry = _registry(
        tmp_path,
        _flow("autodev/flow-project-bootstrap", {"populated": False}),
        _flow("autodev/flow-feature-delivery", {"populated": True}),
    )
    seen: list[str] = []

    def adversarial(task: str, candidates: Any) -> Any:
        seen.extend(c["id"] for c in candidates)
        return {"flow": "autodev/flow-project-bootstrap", "input": {}}

    result = FlowSelector(registry, adversarial).select("start something", POPULATED)
    assert "autodev/flow-project-bootstrap" not in seen
    assert result.outcome == "skipped"
    assert result.eliminated == (
        {"flowId": "autodev/flow-project-bootstrap", "rule": "requires.populated=False"},
    )


def test_matches_flow_surviving_the_gate(tmp_path: Path) -> None:
    registry = _registry(tmp_path, _flow("autodev/flow-project-bootstrap", {"populated": False}))
    result = FlowSelector(
        registry, lambda t, c: '{"flow": "autodev/flow-project-bootstrap", "input": {}}'
    ).select("create a new project", EMPTY)
    assert result.outcome == "matched"
    assert result.flow_id == "autodev/flow-project-bootstrap"


def test_none_is_a_valid_answer(tmp_path: Path) -> None:
    registry = _registry(tmp_path, _flow("autodev/flow-feature-delivery", None))
    result = FlowSelector(registry, lambda t, c: {"flow": "none"}).select("x", POPULATED)
    assert result.outcome == "skipped" and result.reason == "chooser answered none"


def test_provider_error_fails_closed(tmp_path: Path) -> None:
    registry = _registry(tmp_path, _flow("autodev/flow-feature-delivery", None))

    def boom(task: str, candidates: Any) -> Any:
        raise TimeoutError("provider down")

    result = FlowSelector(registry, boom).select("x", POPULATED)
    assert result.outcome == "skipped" and "provider down" in result.reason


def test_unparseable_answer_fails_closed(tmp_path: Path) -> None:
    registry = _registry(tmp_path, _flow("autodev/flow-feature-delivery", None))
    result = FlowSelector(registry, lambda t, c: "I think feature delivery").select("x", POPULATED)
    assert result.outcome == "skipped"


def test_flow_without_applicability_is_never_auto_selected(tmp_path: Path) -> None:
    doc = _flow("autodev/flow-silent", None)
    del doc["purpose"], doc["whenToUse"]
    called: list[Any] = []

    def chooser(task: str, candidates: Any) -> Any:
        called.append(candidates)
        return {"flow": "x"}

    result = FlowSelector(_registry(tmp_path, doc), chooser).select("x", POPULATED)
    assert result.outcome == "skipped" and not called


def test_missing_essential_input_asks_one_question(tmp_path: Path) -> None:
    doc = _flow(
        "autodev/flow-feature-delivery",
        None,
        input={"schemaVersion": "1", "type": "object", "required": ["repo", "ticket"]},
    )
    result = FlowSelector(
        _registry(tmp_path, doc),
        lambda t, c: {"flow": "autodev/flow-feature-delivery", "input": {"repo": "r"}},
    ).select("x", POPULATED)
    assert result.outcome == "question"
    assert "ticket" in result.question and "repo" not in result.question
