"""Tests for the reference agent-coder plugin: files, lifecycle, and v1 parity."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from backend.agents.base import AgentContext
from backend.agents.coder.agent import CoderAgent
from backend.agents.manifest import load_agent_manifest
from backend.agents.registry_v2 import AgentRegistry
from backend.agents.runtime import AgentRuntime
from backend.persistence.database import DurableStore
from backend.plugins.host import PluginHost, PluginState


PLUGIN_DIR = Path("examples/plugins/agent-coder")


def _v1_coder_baseline() -> dict[str, object]:
    """Run the legacy v1 ``CoderAgent`` fallback to capture its baseline output."""
    context = AgentContext(
        session_id="baseline",
        goal="Expose agent contracts",
        user_request="Expose agent contracts",
        artifacts={"planner": {"steps": ["Expose schemas", "Add tests"]}},
    )
    result = CoderAgent().fallback_result(context)
    return {
        "content": result.content,
        "metadata": dict(result.metadata),
    }


def test_reference_agent_coder_plugin_files_and_baseline_are_captured() -> None:
    """The reference plugin's manifests, contracts, and baseline docs are present."""
    assert (PLUGIN_DIR / "plugin.yaml").is_file()
    assert (PLUGIN_DIR / "agent.yaml").is_file()
    assert (PLUGIN_DIR / "contracts" / "coder.input.schema.json").is_file()
    assert (PLUGIN_DIR / "contracts" / "coder.output.schema.json").is_file()
    assert Path("docs/agents/agent-coder-v1-baseline.md").is_file()
    assert Path("docs/sdk/agent-coder-plugin.md").is_file()


def test_agent_coder_plugin_installs_enables_registers_and_uninstalls(tmp_path: Path) -> None:
    """The plugin installs, enables, registers with the agent registry, and uninstalls cleanly."""
    store = DurableStore(f"sqlite:///{tmp_path / 'agent-coder.db'}")
    host = PluginHost(store=store)

    installed = host.install(PLUGIN_DIR)
    enabled = host.enable("autodev/agent-coder")
    registry = AgentRegistry(store)
    registry.sync_from_plugin_store()
    resolved = registry.resolve("autodev/agent-coder", ">=1.0 <2.0")
    uninstalled = host.uninstall("autodev/agent-coder")

    assert installed.state is PluginState.INSTALLED
    assert enabled.state is PluginState.ENABLED
    assert resolved.plugin_id == "autodev/agent-coder"
    assert uninstalled.state is PluginState.UNINSTALLED


def test_agent_coder_plugin_runtime_output_matches_v1_fallback_baseline() -> None:
    """Running the v2 agent through the runtime matches the legacy v1 fallback output."""
    manifest = load_agent_manifest(PLUGIN_DIR / "agent.yaml")
    runtime = AgentRuntime()
    handler = runtime.load_handler(manifest, PLUGIN_DIR)
    baseline = cast(dict[str, Any], _v1_coder_baseline()["metadata"])

    result = runtime.run(
        manifest,
        {
            "schemaVersion": "1.0.0",
            "task": {
                "goal": "Expose agent contracts",
                "userRequest": "Expose agent contracts",
                "plan": ["Expose schemas", "Add tests"],
            },
            "context": {},
        },
        handler,
    )

    assert result.status == "completed"
    assert result.output is not None
    assert result.output["schemaVersion"] == "1.0.0"
    assert result.output["codingTasks"] == baseline["coding_tasks"]
    assert result.output["testUpdates"] == baseline["test_updates"]
    assert result.output["touchedComponents"] == baseline["touched_components"]
