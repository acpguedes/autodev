"""Runtime integration for the provider-neutral model gateway (E2-S6 Task 3)."""

from __future__ import annotations

import pytest

from backend.agents.manifest import AgentManifest, validate_agent_manifest
from backend.agents.provider import StubLLMProvider
from backend.agents.runtime import AgentRuntime, AgentRuntimeContext
from backend.llm import EstimatedCost, ModelProviderNotConfiguredError, TokenUsage
from backend.llm.gateway import ModelGateway
from backend.llm.model_config import ModelConfig, ModelTarget
from backend.llm.registry import ModelProviderRegistry
from backend.llm.stub_provider import StubModelOutput, StubModelProvider


def _manifest(
    *, model: dict | None = None, agent_id: str = "acme/gw-agent"
) -> AgentManifest:
    """Build a valid manifest, optionally carrying schema 2.1 model configuration."""
    raw: dict = {
        "schemaVersion": "2.1" if model else "2.0",
        "kind": "Agent",
        "id": agent_id,
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": "code.implementation", "version": "1.0.0"}],
        "io": {
            "contract": "acme/gw-io",
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
        "entrypoint": {"runtime": "python", "ref": "gw_agent:Agent"},
    }
    if model:
        raw["model"] = model
    result = validate_agent_manifest(raw)
    assert result.valid, result.errors
    assert result.manifest is not None
    return result.manifest


def _payload() -> dict[str, str]:
    """Build a payload matching the test manifest input schema."""
    return {"schemaVersion": "1.0.0", "task": "implement"}


def _handler(ctx: AgentRuntimeContext) -> dict[str, str]:
    """Call the model once and echo its text back as the agent's output."""
    return {"schemaVersion": "1.0.0", "result": ctx.call_llm("hello")}


def _gateway(**responses: StubModelOutput) -> tuple[ModelGateway, StubModelProvider]:
    """Build a gateway over a deterministic offline provider."""
    provider = StubModelProvider(responses=dict(responses))
    return ModelGateway(ModelProviderRegistry({"stub": provider})), provider


def test_legacy_provider_injection_still_works_without_a_gateway() -> None:
    """Existing callers that inject an ``LLMProvider`` are unaffected by E2-S6."""
    runtime = AgentRuntime(
        provider=StubLLMProvider(
            text="legacy", tokens_input=3, tokens_output=2, cost_usd=0.25
        )
    )

    result = runtime.run(_manifest(), _payload(), _handler)

    assert result.status == "completed"
    assert result.output == {"schemaVersion": "1.0.0", "result": "legacy"}
    assert result.metrics["tokens.input"] == 3
    assert result.metrics["cost.usd"] == 0.25


def test_gateway_routes_calls_and_charges_the_run_budget() -> None:
    """A configured gateway replaces the legacy path and still consumes budget."""
    gateway, provider = _gateway(
        m=StubModelOutput(
            text="gatewayed", usage=TokenUsage(4, 6), cost=EstimatedCost(0.5)
        )
    )
    runtime = AgentRuntime(
        gateway=gateway, model_config=ModelConfig(provider="stub", name="m")
    )

    result = runtime.run(_manifest(), _payload(), _handler)

    assert result.output == {"schemaVersion": "1.0.0", "result": "gatewayed"}
    assert result.metrics["tokens.input"] == 4
    assert result.metrics["tokens.output"] == 6
    assert result.metrics["cost.usd"] == 0.5
    assert [call.target.name for call in provider.calls] == ["m"]


def test_two_agents_use_distinct_models_in_one_execution() -> None:
    """Per-agent manifest configuration selects different models in the same runtime."""
    gateway, provider = _gateway(
        fast=StubModelOutput(text="from-fast"),
        deep=StubModelOutput(text="from-deep"),
    )
    runtime = AgentRuntime(
        gateway=gateway, model_config=ModelConfig(provider="stub", name="global")
    )

    fast = runtime.run(
        _manifest(model={"provider": "stub", "name": "fast"}, agent_id="acme/fast"),
        _payload(),
        _handler,
    )
    deep = runtime.run(
        _manifest(model={"provider": "stub", "name": "deep"}, agent_id="acme/deep"),
        _payload(),
        _handler,
    )

    assert fast.output == {"schemaVersion": "1.0.0", "result": "from-fast"}
    assert deep.output == {"schemaVersion": "1.0.0", "result": "from-deep"}
    assert [call.target.name for call in provider.calls] == ["fast", "deep"]


def test_execution_override_beats_agent_which_beats_global() -> None:
    """The approved precedence holds end to end through the runtime."""
    gateway, provider = _gateway(
        override=StubModelOutput(text="override"),
        agent=StubModelOutput(text="agent"),
        globaldefault=StubModelOutput(text="global"),
    )
    runtime = AgentRuntime(
        gateway=gateway,
        model_config=ModelConfig(provider="stub", name="globaldefault"),
    )
    configured = _manifest(model={"provider": "stub", "name": "agent"})

    def _result_text(manifest: AgentManifest, **kwargs: object) -> str:
        outcome = runtime.run(manifest, _payload(), _handler, **kwargs)  # type: ignore[arg-type]
        assert outcome.output is not None
        return str(outcome.output["result"])

    assert (
        _result_text(
            configured, model_override=ModelConfig(provider="stub", name="override")
        )
        == "override"
    )
    assert _result_text(configured) == "agent"
    assert _result_text(_manifest()) == "global"
    assert [call.target.name for call in provider.calls] == [
        "override",
        "agent",
        "globaldefault",
    ]


def test_run_metrics_expose_model_attempts_and_failures() -> None:
    """Attempt telemetry is aggregated into the run result, including fallbacks."""
    provider = StubModelProvider(
        responses={
            "primary": ModelProviderNotConfiguredError("cold"),
            "safe": StubModelOutput(text="recovered", usage=TokenUsage(1, 1)),
        }
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))
    runtime = AgentRuntime(
        gateway=gateway,
        model_config=ModelConfig(
            provider="stub",
            name="primary",
            fallback_on=("provider_not_configured",),
            fallback=(ModelTarget(provider="stub", name="safe"),),
        ),
    )

    result = runtime.run(_manifest(), _payload(), _handler)

    assert result.output is not None
    assert result.output["result"] == "recovered"
    assert result.metrics["model.attempts"] == 2
    assert result.metrics["model.failures"] == 1
    assert result.metrics["model.latency_ms"] >= 0


def test_missing_model_configuration_fails_the_run_explicitly() -> None:
    """No override, no manifest model, and no global default is an explicit error."""
    gateway, _ = _gateway(m=StubModelOutput(text="unused"))
    runtime = AgentRuntime(gateway=gateway)

    result = runtime.run(_manifest(), _payload(), _handler)

    assert result.status == "failed"
    assert result.stop_reason == "handler_failed"


def test_gateway_errors_do_not_leak_credentials_into_the_run_result() -> None:
    """A failing provider must not put credentials into run steps or details."""
    secret = "hunter2hunter2secret"
    provider = StubModelProvider(
        responses={
            "m": ModelProviderNotConfiguredError(
                f"401 {{'api_key': '{secret}'}} rejected"
            )
        }
    )
    gateway = ModelGateway(ModelProviderRegistry({"stub": provider}))
    runtime = AgentRuntime(
        gateway=gateway, model_config=ModelConfig(provider="stub", name="m")
    )

    result = runtime.run(_manifest(), _payload(), _handler)

    assert result.status == "failed"
    assert secret not in str(result.steps)


@pytest.mark.parametrize("schema_version", ["2.0", "2.1"])
def test_both_manifest_schema_versions_run_under_the_gateway(
    schema_version: str,
) -> None:
    """Schema 2.0 manifests keep working; 2.1 adds model selection."""
    gateway, _ = _gateway(
        chosen=StubModelOutput(text="ok"), fallbackname=StubModelOutput(text="ok")
    )
    runtime = AgentRuntime(
        gateway=gateway, model_config=ModelConfig(provider="stub", name="fallbackname")
    )
    manifest = (
        _manifest()
        if schema_version == "2.0"
        else _manifest(model={"provider": "stub", "name": "chosen"})
    )

    outcome = runtime.run(manifest, _payload(), _handler)
    assert outcome.output is not None
    assert outcome.output["result"] == "ok"
