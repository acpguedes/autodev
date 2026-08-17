"""Alpha wave-gate evidence: agent-plugin flow, durable state, event replay.

The v2.0-alpha gate's first criterion reads: "A declarative flow executes an
agent-plugin end to end with durable state and event-store replay." Both halves
were already covered, but in separate tests over different flows -- an
agent-plugin flow without the event store
(``backend/tests/unit/flows/test_flows_api.py``), and event-store
reconstruction plus deterministic replay over a *skill* node
(``backend/tests/unit/events/test_event_store.py``). Nothing exercised the
sentence as written.

This test is that single piece of evidence: the real ``autodev/agent-coder``
reference plugin, resolved through the E2 Agent Registry, executed by the E3
Flow Engine against a durable SQLite store, with the Event Store enabled, then
reconstructed from stored events and replayed deterministically.

**Defect this test surfaced (2026-08-17).** ``PluginPermissions.import_sandbox``
patches ``builtins.__import__`` while an in-process plugin loads and denies any
import whose root module is in ``NETWORK_MODULES``. It does not distinguish the
plugin's *own* network use from a **transitive import of the host backend**,
which the ``in-process`` loader exists to allow. ``autodev/agent-coder`` imports
``backend.agents.coder.agent``, whose transitive imports reach ``urllib``, so a
cold process quarantines the reference plugin with "network imports require
permissions.network.egress". A running server never hits this because those host
modules are already in ``sys.modules`` by the time a plugin is enabled --
``__import__`` returns the cached module without executing the body that would
trip the guard. The pre-import below reproduces the server's condition
deliberately rather than relying on test ordering; the existing
``test_flows_api.py::TestAgentFlowEndToEnd`` passes only because earlier tests in
that file happen to load the same modules first, and fails when run alone. The
sandbox scoping is a security-boundary decision, so it is recorded in
``docs/v2_platform/progress.md`` rather than changed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from backend.agents.registry_v2 import AgentRegistry
from backend.config.settings import reset_settings_cache
from backend.events.runtime import (
    get_event_store,
    reset_event_bus_for_tests,
    reset_event_store_for_tests,
)
from backend.flows.engine import FlowEngine
from backend.flows.handlers import AgentNodeHandler, build_default_handlers
from backend.persistence.database import reset_store_cache
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.plugins.host import PluginHost

#: The E2 reference agent plugin shipped in this repository.
PLUGIN_DIR = Path("examples/plugins/agent-coder")

_FLOW_MANIFEST: dict[str, Any] = {
    "schemaVersion": "1",
    "id": "autodev/flow-alpha-gate",
    "version": "1.0.0",
    "hostApi": ">=2.0 <3.0",
    "input": {
        "type": "object",
        "required": ["goal"],
        "properties": {"goal": {"type": "string"}},
    },
    "nodes": [
        {
            "id": "code",
            "type": "agent",
            "ref": "autodev/agent-coder@>=1.0 <2.0",
            "input": {
                "schemaVersion": "1.0.0",
                "task": {
                    "goal": "{{ flow.input.goal }}",
                    "userRequest": "{{ flow.input.goal }}",
                    "plan": ["Expose schemas", "Add tests"],
                },
                "context": {},
            },
        }
    ],
    "edges": [],
}


def _preload_plugin_host_dependencies() -> None:
    """Import the host modules ``autodev/agent-coder`` depends on.

    Reproduces a running server's state, where these are already loaded before
    any plugin is enabled. Without it the plugin's import sandbox denies the
    transitive host imports and quarantines the plugin -- see this module's
    docstring.
    """
    import backend.agents.coder.agent  # noqa: F401
    import backend.agents.runtime  # noqa: F401
    import backend.sdk.contracts  # noqa: F401


def test_agent_plugin_flow_is_durable_and_replays_from_the_event_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alpha gate criterion 1, exercised as one end-to-end path."""
    database_url = f"sqlite:///{tmp_path / 'alpha_gate.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    # Defaults: in-memory bus, event store on. Cleared so the test does not
    # inherit a developer's Redis or opt-out configuration.
    monkeypatch.delenv("AUTODEV_EVENT_BUS", raising=False)
    monkeypatch.delenv("AUTODEV_EVENT_STORE_ENABLED", raising=False)
    reset_settings_cache()
    reset_store_cache()
    reset_event_bus_for_tests()
    reset_event_store_for_tests()

    try:
        _preload_plugin_host_dependencies()

        store = SQLiteStore(database_url)
        host = PluginHost(store=store)
        host.install(PLUGIN_DIR)
        enabled = host.enable("autodev/agent-coder")
        # Fail here rather than 40 lines later on an opaque resolve error.
        assert enabled.state.value == "enabled", enabled.reason
        registry = AgentRegistry(store)
        registry.sync_from_plugin_store()

        engine = FlowEngine(
            store=store,
            handlers=build_default_handlers(
                store=store,
                agent_handler=AgentNodeHandler(agent_registry=registry, store=store),
            ),
        )
        engine.registry.register_raw(_FLOW_MANIFEST)

        run = engine.start_run(
            "autodev/flow-alpha-gate", input={"goal": "Expose agent contracts"}
        )

        # 1. The agent plugin actually ran and produced its typed output.
        assert run.status == "completed"
        output = cast(dict[str, Any], run.output)
        assert output["codingTasks"]

        # 2. Durable state: the step trail survives in the store.
        recorded_steps = engine.runs.list_steps(run.run_id)
        assert [step.node_type for step in recorded_steps] == ["agent"]

        # 3. Event-store reconstruction: the run view is rebuilt from stored
        #    events alone, independently of the run tables above.
        view = get_event_store().reconstruct_run(run.run_id)
        assert view["status"] == run.status
        assert [step["stepKey"] for step in view["steps"]] == [
            step.node_id for step in recorded_steps if step.status == "completed"
        ]

        # 4. Replay is deterministic.
        report = engine.replay_run(run.run_id)
        assert report.deterministic, report.divergences
    finally:
        reset_settings_cache()
        reset_store_cache()
        reset_event_bus_for_tests()
        reset_event_store_for_tests()
