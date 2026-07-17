"""Tests for the v2 agent runtime: budgets, guardrails, tools, and metrics."""

from __future__ import annotations

from backend.agents.manifest import DEFAULT_AGENT_BUDGETS, AgentManifest, validate_agent_manifest
from backend.agents.runtime import AgentRuntime, AgentRuntimeContext


def _runtime_manifest(*, policy: dict | None = None, max_steps: int | None = None) -> AgentManifest:
    """Build a valid agent manifest for runtime tests, with optional policy/budget overrides."""
    budgets = {}
    if max_steps is not None:
        budgets = {"maxSteps": max_steps}
    raw = {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": "acme/runtime-agent",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": "code.implementation", "version": "1.0.0"}],
        "io": {
            "contract": "acme/runtime-io",
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
                "required": ["schemaVersion", "status", "result"],
                "properties": {
                    "schemaVersion": {"const": "1.0.0"},
                    "status": {"enum": ["ok", "error"]},
                    "result": {"type": "string"},
                },
            },
        },
        "policy": policy or {},
        "budgets": budgets,
        "entrypoint": {"runtime": "python", "ref": "runtime_agent:Agent"},
    }
    result = validate_agent_manifest(raw)
    assert result.valid, result.errors
    assert result.manifest is not None
    return result.manifest


def _payload() -> dict[str, str]:
    """Build a minimal valid input payload matching the test manifest's input schema."""
    return {"schemaVersion": "1.0.0", "task": "implement"}


def test_runtime_uses_safe_default_budgets_when_manifest_omits_them() -> None:
    """A manifest without explicit budgets falls back to the safe defaults."""
    manifest = _runtime_manifest()
    runtime = AgentRuntime()

    result = runtime.run(manifest, _payload(), lambda ctx: {"schemaVersion": "1.0.0", "status": "ok", "result": "done"})

    assert result.status == "completed"
    assert result.budgets.max_steps == DEFAULT_AGENT_BUDGETS.max_steps
    assert result.metrics["tokens.input"] == 0
    assert result.steps[-1].name == "validate-output"


def test_runtime_interrupts_and_flags_budget_overrun() -> None:
    """Exceeding the max-steps budget interrupts the run and flags it for review."""
    manifest = _runtime_manifest(max_steps=2)
    runtime = AgentRuntime()

    def noisy_handler(ctx: AgentRuntimeContext) -> dict[str, str]:
        """Record more steps than the manifest's budget allows."""
        ctx.record_step("plan", status="completed")
        ctx.record_step("act", status="completed")
        ctx.record_step("extra", status="completed")
        return {"schemaVersion": "1.0.0", "status": "ok", "result": "unreachable"}

    result = runtime.run(manifest, _payload(), noisy_handler)

    assert result.status == "interrupted"
    assert result.stop_reason == "budget_exhausted"
    assert result.flagged is True
    assert result.steps[-1].status == "failed"
    assert result.steps[-1].reason == "budget_exhausted"


def test_runtime_blocks_guardrail_violation_and_records_failed_step() -> None:
    """A denylist guardrail match blocks the run and records a failed step."""
    manifest = _runtime_manifest(policy={"guardrails": [{"type": "denylist", "terms": ["SECRET"], "onViolation": "block"}]})
    runtime = AgentRuntime()

    result = runtime.run(
        manifest,
        _payload(),
        lambda ctx: {"schemaVersion": "1.0.0", "status": "ok", "result": "contains SECRET"},
    )

    assert result.status == "blocked"
    assert result.stop_reason == "guardrail_blocked"
    assert result.output is None
    assert result.steps[-1].name == "guardrail-output"
    assert result.steps[-1].status == "failed"


def test_runtime_rejects_output_outside_schema() -> None:
    """Output with an undeclared property fails validation and fails the run."""
    manifest = _runtime_manifest()
    runtime = AgentRuntime()

    result = runtime.run(
        manifest,
        _payload(),
        lambda ctx: {"schemaVersion": "1.0.0", "status": "ok", "result": "done", "extra": "nope"},
    )

    assert result.status == "failed"
    assert result.stop_reason == "invalid_output"
    assert "additional property extra is not allowed" in result.steps[-1].detail


def test_runtime_records_token_cost_metrics_per_run_and_tenant() -> None:
    """Manually consumed budget is reflected in the run's metrics, run id, and tenant id."""
    manifest = _runtime_manifest()
    runtime = AgentRuntime()

    def metered_handler(ctx: AgentRuntimeContext) -> dict[str, str]:
        """Consume a fixed amount of token/cost budget and return a valid output."""
        ctx.consume_budget(tokens_input=12, tokens_output=5, cost_usd=0.03)
        return {"schemaVersion": "1.0.0", "status": "ok", "result": "done"}

    result = runtime.run(manifest, _payload(), metered_handler, run_id="run-1", tenant_id="tenant-a")

    assert result.run_id == "run-1"
    assert result.tenant_id == "tenant-a"
    assert result.metrics == {
        "tokens.input": 12,
        "tokens.output": 5,
        "cost.usd": 0.03,
        "tool.calls": 0,
        "steps": len(result.steps),
    }
