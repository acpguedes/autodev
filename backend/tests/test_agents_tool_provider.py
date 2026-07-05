from __future__ import annotations

import pytest

from backend.agents.manifest import validate_agent_manifest
from backend.agents.provider import LLMProviderResponse, StubLLMProvider
from backend.agents.runtime import AgentRuntime, AgentRuntimeContext
from backend.agents.tools import AgentToolBroker, ToolAccessDenied


def _manifest_with_tool(tool_id: str = "fs.read"):
    raw = {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": "acme/tool-agent",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": "code.implementation", "version": "1.0.0"}],
        "io": {
            "contract": "acme/tool-io",
            "contractVersion": "1.0.0",
            "input": {"type": "object", "additionalProperties": True},
            "output": {
                "type": "object",
                "additionalProperties": False,
                "required": ["schemaVersion", "status", "result"],
                "properties": {
                    "schemaVersion": {"const": "1.0.0"},
                    "status": {"enum": ["ok", "error"]},
                    "result": {"type": "string"},
                },
            },
        },
        "permissions": {
            "network": "none",
            "tools": [{"id": tool_id}],
            "skills": [{"id": "autodev/skill-unified-diff", "versionRange": ">=1.0 <2.0"}],
        },
        "entrypoint": {"runtime": "python", "ref": "tool_agent:Agent"},
    }
    result = validate_agent_manifest(raw)
    assert result.valid, result.errors
    assert result.manifest is not None
    return result.manifest


def test_tool_broker_denies_undeclared_tools_and_network_by_default() -> None:
    manifest = _manifest_with_tool()
    broker = AgentToolBroker(manifest, tools={"fs.read": lambda path: f"read:{path}"})

    assert broker.call_tool("fs.read", path="README.md") == "read:README.md"
    with pytest.raises(ToolAccessDenied):
        broker.call_tool("fs.write", path="README.md")
    with pytest.raises(ToolAccessDenied):
        broker.open_network("example.com", 443)


def test_runtime_injects_only_granted_tools_into_agent_context() -> None:
    manifest = _manifest_with_tool()
    runtime = AgentRuntime(tools={"fs.read": lambda path: f"read:{path}"})

    def handler(ctx: AgentRuntimeContext) -> dict[str, str]:
        return {
            "schemaVersion": "1.0.0",
            "status": "ok",
            "result": ctx.call_tool("fs.read", path="README.md"),
        }

    result = runtime.run(manifest, {}, handler)

    assert result.status == "completed"
    assert result.output is not None
    assert result.output["result"] == "read:README.md"
    assert result.metrics["tool.calls"] == 1


def test_stub_provider_runs_offline_and_meters_tokens_and_cost() -> None:
    manifest = _manifest_with_tool()
    runtime = AgentRuntime(provider=StubLLMProvider(text="stubbed", tokens_input=3, tokens_output=2, cost_usd=0.01))

    def handler(ctx: AgentRuntimeContext) -> dict[str, str]:
        text = ctx.call_llm("draft patch")
        return {"schemaVersion": "1.0.0", "status": "ok", "result": text}

    result = runtime.run(manifest, {}, handler, run_id="run-s4", tenant_id="tenant-s4")

    assert result.output is not None
    assert result.output["result"] == "stubbed"
    assert result.metrics["tokens.input"] == 3
    assert result.metrics["tokens.output"] == 2
    assert result.metrics["cost.usd"] == 0.01
    assert result.run_id == "run-s4"
    assert result.tenant_id == "tenant-s4"


def test_mocked_real_provider_uses_same_agent_code_as_stub() -> None:
    class MockRealProvider:
        def complete(self, prompt: str, *, agent_id: str, run_id: str, tenant_id: str) -> LLMProviderResponse:
            assert prompt == "draft patch"
            assert agent_id == "acme/tool-agent"
            return LLMProviderResponse(text=f"real:{run_id}:{tenant_id}", tokens_input=7, tokens_output=4, cost_usd=0.05)

    manifest = _manifest_with_tool()
    runtime = AgentRuntime(provider=MockRealProvider())

    def handler(ctx: AgentRuntimeContext) -> dict[str, str]:
        text = ctx.call_llm("draft patch")
        return {"schemaVersion": "1.0.0", "status": "ok", "result": text}

    result = runtime.run(manifest, {}, handler, run_id="run-real", tenant_id="tenant-real")

    assert result.output is not None
    assert result.output["result"] == "real:run-real:tenant-real"
    assert result.metrics["tokens.input"] == 7
    assert result.metrics["tokens.output"] == 4
    assert result.metrics["cost.usd"] == 0.05
