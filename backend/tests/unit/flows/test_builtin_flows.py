"""E63-S5: built-in flows validate, seed idempotently, and have resolvable refs."""

from __future__ import annotations

from backend.flows.model import FlowRequires

from pathlib import Path
from typing import Any

import yaml

from backend.flows.builtin import load_builtin_flows, seed_builtin_flows
from backend.flows.model import version_in_range
from backend.flows.registry import FlowRegistry
from backend.persistence.database import SQLiteStore

REPO_ROOT = Path(__file__).resolve().parents[4]
PLUGINS = REPO_ROOT / "examples" / "plugins"

# Refs the built-in flows use that no shipped plugin provides yet; declared in
# docs/v2_platform/phases/e63_flow_applicability_routing.md (E63-S5-T3).
DECLARED_GAPS = {
    "autodev/agent-planner",
    "autodev/skill-run-eval",
    "autodev/skill-notify",
}


def _registry(tmp_path: Path) -> FlowRegistry:
    return FlowRegistry(SQLiteStore(f"sqlite:///{tmp_path / 'builtin.db'}"))


def _shipped_artifacts() -> dict[str, str]:
    shipped: dict[str, str] = {}
    for name in ("agent.yaml", "skill.yaml"):
        for path in PLUGINS.glob(f"*/{name}"):
            doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
            shipped[doc["id"]] = str(doc["version"])
    return shipped


def test_builtins_validate_and_declare_applicability() -> None:
    flows = {m.id: m for m in load_builtin_flows()}
    assert set(flows) == {"autodev/flow-project-bootstrap", "autodev/flow-feature-delivery"}
    assert (flows["autodev/flow-project-bootstrap"].requires or FlowRequires()).populated is False
    assert (flows["autodev/flow-feature-delivery"].requires or FlowRequires()).populated is True
    assert all(m.auto_selectable for m in flows.values())
    assert "existing codebase" in flows["autodev/flow-project-bootstrap"].when_not_to_use


def test_seeding_twice_leaves_one_entry_per_version(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    assert len(seed_builtin_flows(registry)) == 2
    assert seed_builtin_flows(registry) == []
    listed = registry.list_flows()
    assert sorted((m.id, m.version) for m in listed) == [
        ("autodev/flow-feature-delivery", "1.0.0"),
        ("autodev/flow-project-bootstrap", "1.0.0"),
    ]


def test_seeding_never_overwrites_user_published_version(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    raw = next(m.raw for m in load_builtin_flows() if m.id == "autodev/flow-feature-delivery")
    raw = dict(raw)
    raw["name"] = "User Edited"
    registry.register_raw(raw)
    seed_builtin_flows(registry)
    assert registry.resolve("autodev/flow-feature-delivery").name == "User Edited"


def test_every_node_ref_resolves_or_is_a_declared_gap() -> None:
    shipped = _shipped_artifacts()
    unresolved: set[str] = set()
    for manifest in load_builtin_flows():
        for node in manifest.nodes:
            if node.ref is None:
                continue
            version = shipped.get(node.ref.id)
            if version is None:
                unresolved.add(node.ref.id)
            else:
                assert version_in_range(version, node.ref.version_range), (manifest.id, node.id)
    assert unresolved <= DECLARED_GAPS
    # The bootstrap flow must be fully runnable on a default install.
    bootstrap = next(m for m in load_builtin_flows() if m.id == "autodev/flow-project-bootstrap")
    assert all(n.ref is None or n.ref.id in shipped for n in bootstrap.nodes)
