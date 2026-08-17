"""End-to-end proof that the model gateway is reachable from a flow run (E2-S6).

E2-S6's completion criterion is that two agents can use distinct models within a
single execution. Before the composition root existed, no production path built
a :class:`~backend.llm.gateway.ModelGateway` at all, so the criterion was
unsatisfiable by any route and the epic's "Done" status overstated what shipped.

Network avoidance here is structural rather than mocked:
:class:`~backend.llm.stub_provider.StubModelProvider` is pure Python and is
keyed by model name, so a green assertion genuinely proves that two *different*
models were selected — had precedence resolution picked the wrong one, the stub
would raise instead of quietly returning a generic string.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from backend.agents.manifest import AgentManifest, validate_agent_manifest
from backend.agents.registry_v2 import AgentRegistry
from backend.agents.runtime import AgentRuntime, AgentRuntimeContext
from backend.config.runtime import LLMSettings, get_runtime_config_service
from backend.flows.engine import FlowEngine
from backend.flows.handlers import AgentNodeHandler, build_default_handlers
from backend.llm.composition import (
    build_agent_runtime,
    get_global_model_config,
    get_model_gateway,
    reset_model_composition_cache,
)
from backend.llm.gateway import ModelGateway
from backend.llm.model_config import ModelConfig
from backend.llm.registry import ModelProviderRegistry
from backend.llm.stub_provider import StubModelProvider
from backend.persistence.sqlite_adapter import SQLiteStore

PLUGIN_ID = "acme/model-agents"


def _manifest(agent_id: str, model_name: str) -> AgentManifest:
    """Build a schema 2.1 agent manifest bound to one model.

    Args:
        agent_id: Fully qualified agent id.
        model_name: Model name the agent declares in its manifest.

    Returns:
        The validated manifest.
    """
    result = validate_agent_manifest(
        {
            "schemaVersion": "2.1",
            "kind": "Agent",
            "id": agent_id,
            "version": "1.0.0",
            "hostApi": ">=2.0 <3.0",
            "capabilities": [{"id": "code.implementation", "version": "1.0.0"}],
            "io": {
                "contract": "acme/model-io",
                "contractVersion": "1.0.0",
                "input": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["schemaVersion", "task"],
                    "properties": {
                        "schemaVersion": {"const": "1.0.0"},
                        "task": {"type": "string", "minLength": 1},
                    },
                },
                "output": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["schemaVersion", "result"],
                    "properties": {
                        "schemaVersion": {"const": "1.0.0"},
                        "result": {"type": "string"},
                    },
                },
            },
            "policy": {},
            "budgets": {},
            "entrypoint": {"runtime": "python", "ref": "model_agent:Agent"},
            "model": {"provider": "stub", "name": model_name},
        }
    )
    assert result.valid, result.errors
    assert result.manifest is not None
    return result.manifest


def _handler(ctx: AgentRuntimeContext) -> dict[str, str]:
    """Call the model once and echo its text back as the agent output.

    Args:
        ctx: The agent runtime activation context.

    Returns:
        An output payload matching the test manifest's output schema.
    """
    return {"schemaVersion": "1.0.0", "result": ctx.call_llm("hello")}


def _agent_node(node_id: str, agent_id: str) -> dict[str, Any]:
    """Build one ``agent`` flow node targeting the given agent.

    Args:
        node_id: Flow-local node id.
        agent_id: Agent the node dispatches to.

    Returns:
        The raw node declaration.
    """
    return {
        "id": node_id,
        "type": "agent",
        "ref": f"{agent_id}@>=1.0 <2.0",
        "input": {"schemaVersion": "1.0.0", "task": "implement"},
    }


def _persist_llm_settings(provider: str, model: str) -> None:
    """Persist an LLM configuration and invalidate the composition caches.

    Args:
        provider: Provider id to store in the runtime configuration.
        model: Model name to store in the runtime configuration.
    """
    service = get_runtime_config_service()
    current = service.load()
    service.update(current.model_copy(update={"llm": LLMSettings(provider=provider, model=model)}))
    reset_model_composition_cache()


class TestGatewayReachableFromAFlowRun:
    """The E2-S6 completion criterion, exercised through the flow engine."""

    def test_two_agents_use_distinct_models_in_one_flow_run(self, tmp_path: Path) -> None:
        """Two agent nodes in one run each reach their own manifest-declared model.

        This also proves the "explicit injection still wins" contract: the
        handler is given its own runtime, which must override the composed
        default.
        """
        store = SQLiteStore(f"sqlite:///{tmp_path / 'gateway.db'}")
        registry = AgentRegistry(store)
        registry.register(_manifest("acme/fast-agent", "fast"), plugin_id=PLUGIN_ID)
        registry.register(_manifest("acme/deep-agent", "deep"), plugin_id=PLUGIN_ID)

        provider = StubModelProvider(
            responses={"fast": "from-fast", "deep": "from-deep"}
        )
        runtime = AgentRuntime(gateway=ModelGateway(ModelProviderRegistry({"stub": provider})))
        agent_handler = AgentNodeHandler(
            agent_registry=registry,
            agent_runtime=runtime,
            local_handlers={
                "acme/fast-agent": _handler,
                "acme/deep-agent": _handler,
            },
        )
        engine = FlowEngine(
            store=store,
            handlers=build_default_handlers(store=store, agent_handler=agent_handler),
        )
        engine.registry.register_raw(
            {
                "schemaVersion": "1",
                "id": "acme/two-models",
                "version": "1.0.0",
                "hostApi": ">=2.0 <3.0",
                "input": {"type": "object", "properties": {}},
                "nodes": [
                    _agent_node("first", "acme/fast-agent"),
                    _agent_node("second", "acme/deep-agent"),
                ],
                "edges": [{"from": "first", "to": "second"}],
            }
        )

        run = engine.start_run("acme/two-models", input={})

        assert run.status == "completed"
        assert [call.target.name for call in provider.calls] == ["fast", "deep"]
        assert [step.node_type for step in engine.runs.list_steps(run.run_id)] == [
            "agent",
            "agent",
        ]
        output = cast(dict[str, Any], run.output)
        assert output["result"] == "from-deep"

    def test_composed_runtime_is_the_default_for_agent_nodes(self, tmp_path: Path) -> None:
        """Without explicit injection the handler composes its runtime.

        The offline profile composes no gateway, so this asserts the seam is
        used — not that a gateway exists.
        """
        _persist_llm_settings("stub", "irrelevant")
        store = SQLiteStore(f"sqlite:///{tmp_path / 'default.db'}")
        handler = AgentNodeHandler(agent_registry=AgentRegistry(store), store=store)

        assert handler._runtime._gateway is None
        assert build_agent_runtime()._gateway is None


class TestConfiguredProviderReachesComposition:
    """The configured model must flow from the versioned API into the gateway."""

    def test_configured_provider_model_reaches_the_gateway(self) -> None:
        """A model set through the runtime config becomes the global default.

        No model call is issued here — this asserts wiring, not behavior.
        """
        _persist_llm_settings("ollama", "llama3.1")

        assert isinstance(get_model_gateway(), ModelGateway)
        assert get_global_model_config() == ModelConfig(provider="ollama", name="llama3.1")

    def test_stub_provider_composes_without_a_gateway(self) -> None:
        """The offline profile stays first-class after composition."""
        _persist_llm_settings("stub", "irrelevant")

        assert get_model_gateway() is None


class TestConfigWritesInvalidateComposition:
    """Every surface that writes the LLM block must invalidate the caches."""

    @pytest.fixture
    def client(self) -> Any:
        """Build a test client for the versioned API.

        Returns:
            A ``TestClient`` bound to the FastAPI application.
        """
        from fastapi.testclient import TestClient

        from backend.api.main import app

        return TestClient(app)

    def test_provider_config_put_invalidates_the_composed_gateway(
        self, client: Any
    ) -> None:
        """``PUT /v2/provider-config`` must rebuild the gateway, not reuse it."""
        _persist_llm_settings("stub", "irrelevant")
        assert get_model_gateway() is None

        response = client.put(
            "/v2/provider-config",
            json={"llm": {"provider": "ollama", "model": "llama3.1"}},
        )

        assert response.status_code == 200
        assert isinstance(get_model_gateway(), ModelGateway)
        assert get_global_model_config() == ModelConfig(provider="ollama", name="llama3.1")
