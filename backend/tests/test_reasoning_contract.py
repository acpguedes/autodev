"""Contract tests for the E4-S1 Reasoning Engine and Strategy contract.

Covers the story DoD: a conforming strategy runs end-to-end through the
:class:`ReasoningEngine` and yields ``stop_reason="completed"`` with an ordered
trace; budgets fail closed with no external effect past the ceiling; guardrail
``block``/``warn``/``repair_once`` actions behave per policy; the strategy
registry resolves SemVer versions and rejects host-incompatible strategies; and
the published manifest/policy schemas validate their documents.

The reasoning contract is ``async`` (ADR-007); tests drive it with
:func:`asyncio.run` so no async test framework dependency is required.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from backend.agents.provider import LLMProviderResponse, StubLLMProvider
from backend.reasoning import (
    Budget,
    GuardrailSpec,
    ReasoningContext,
    ReasoningEngine,
    ReasoningInput,
    ReasoningOutput,
    ReasoningStrategyRegistry,
    TraceEvent,
    Usage,
    budget_from_policy,
    default_reasoning_policy,
    is_host_compatible,
)
from backend.reasoning.contract import (
    REASONING_CONTRACT_HOST_API,
    STOP_REASONS,
    validate_reasoning_strategy_manifest,
)
from backend.reasoning.policy import validate_reasoning_policy

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "reasoning" / "schemas"


# --------------------------------------------------------------------------
# Test strategies
# --------------------------------------------------------------------------


class _EchoStrategy:
    """Minimal conforming strategy: one LLM call, echoes the completion."""

    id = "autodev/reasoning-echo"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def config_schema(self) -> dict[str, Any]:
        """Return an empty configuration schema."""
        return {"type": "object", "properties": {}}

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Emit a thought, call the LLM once, and return its completion."""
        ctx.emit(TraceEvent(sequence=0, name="reasoning.step.thought", payload={"task": input.task}, timestamp=0.0))
        result = await ctx.call_llm([{"role": "user", "content": input.task}])
        return ReasoningOutput(content=result.content, stop_reason="completed", usage=Usage(), trace_id="")


class _LoopStrategy:
    """Non-terminating strategy used to exercise fail-closed budgets."""

    id = "autodev/reasoning-loop"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def config_schema(self) -> dict[str, Any]:
        """Return an empty configuration schema."""
        return {"type": "object"}

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Call the LLM far more times than any budget allows."""
        for _ in range(1000):
            await ctx.call_llm([{"role": "user", "content": "again"}])
        return ReasoningOutput(content="unreachable", stop_reason="completed", usage=Usage(), trace_id="")


class _FixedContentStrategy:
    """Strategy that returns a fixed content payload without calling the LLM."""

    id = "autodev/reasoning-fixed"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def __init__(self, content: str) -> None:
        """Store the fixed content the strategy will return."""
        self._content = content

    def config_schema(self) -> dict[str, Any]:
        """Return an empty configuration schema."""
        return {"type": "object"}

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Return the configured content unchanged."""
        return ReasoningOutput(content=self._content, stop_reason="completed", usage=Usage(), trace_id="")


class _RepairStrategy:
    """Strategy that self-repairs when its first output violates a guardrail."""

    id = "autodev/reasoning-repair"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def config_schema(self) -> dict[str, Any]:
        """Return an empty configuration schema."""
        return {"type": "object"}

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Verify a bad candidate, repair it once, and return the good output."""
        candidate = "BAD output"
        verdict = await ctx.verify(candidate)
        if not verdict.passed and verdict.action == "repair_once":
            candidate = "GOOD output"
        return ReasoningOutput(content=candidate, stop_reason="completed", usage=Usage(), trace_id="")


class _CountingProvider:
    """LLM provider that counts calls to assert fail-closed no-effect behavior."""

    def __init__(self) -> None:
        """Initialize the call counter."""
        self.calls = 0

    def complete(self, prompt: str, *, agent_id: str, run_id: str, tenant_id: str) -> LLMProviderResponse:
        """Increment the counter and return a fixed one-token response."""
        self.calls += 1
        return LLMProviderResponse(text="x", tokens_input=1, tokens_output=1, cost_usd=0.0)


def _make_input(
    *,
    task: str = "do the thing",
    policy: Any = None,
    budget: Budget | None = None,
) -> ReasoningInput:
    """Build a :class:`ReasoningInput` with defaults for tests."""
    policy = policy or default_reasoning_policy(default_strategy="autodev/reasoning-echo")
    return ReasoningInput(
        task=task,
        messages=(),
        tools=(),
        policy=policy,
        budget=budget or budget_from_policy(policy),
    )


# --------------------------------------------------------------------------
# Contract surface
# --------------------------------------------------------------------------


def test_contract_constants() -> None:
    """The contract exposes the expected version range and stop reasons."""
    assert REASONING_CONTRACT_HOST_API == ">=2.0 <3.0"
    assert STOP_REASONS == {"completed", "budget_exhausted", "guardrail_blocked", "error"}


# --------------------------------------------------------------------------
# Engine execution
# --------------------------------------------------------------------------


def test_engine_runs_strategy_to_completion() -> None:
    """A conforming strategy runs end-to-end and reports authoritative usage."""
    events: list[TraceEvent] = []
    engine = ReasoningEngine(
        provider=StubLLMProvider(text="hello", tokens_input=10, tokens_output=5, cost_usd=0.02),
        on_event=events.append,
    )
    output = asyncio.run(engine.run(_EchoStrategy(), _make_input()))

    assert output.stop_reason == "completed"
    assert output.content == "hello"
    assert output.usage.tokens == 15
    assert output.usage.steps == 1
    assert output.trace_id
    # Trace is ordered (strictly increasing sequence) and framed by run events.
    assert [event.sequence for event in events] == list(range(len(events)))
    assert events[0].name == "reasoning.run.started"
    assert events[-1].name == "reasoning.run.completed"
    assert any(event.name == "reasoning.llm.called" for event in events)


def test_budget_fails_closed_with_no_effect_past_ceiling() -> None:
    """Once the step budget is reached, no further LLM call is made."""
    provider = _CountingProvider()
    engine = ReasoningEngine(provider=provider)
    budget = Budget(tokens=10_000, cost_usd=100.0, wall_clock_ms=60_000, max_steps=3)
    output = asyncio.run(engine.run(_LoopStrategy(), _make_input(budget=budget)))

    assert output.stop_reason == "budget_exhausted"
    assert output.usage.steps == 3
    # Fail-closed: exactly max_steps effects occurred, none after the ceiling.
    assert provider.calls == 3


def test_guardrail_block_stops_run() -> None:
    """A blocking guardrail terminates the run with guardrail_blocked."""
    policy = default_reasoning_policy(guardrails=(GuardrailSpec("no_secret_leakage", "block"),))
    engine = ReasoningEngine(
        guardrail_checks={"no_secret_leakage": lambda out: "SECRET" not in str(out)},
    )
    output = asyncio.run(
        engine.run(_FixedContentStrategy("here is a SECRET"), _make_input(policy=policy))
    )
    assert output.stop_reason == "guardrail_blocked"


def test_guardrail_warn_allows_completion() -> None:
    """A warn guardrail records a violation but does not stop the run."""
    policy = default_reasoning_policy(guardrails=(GuardrailSpec("style", "warn"),))
    engine = ReasoningEngine(guardrail_checks={"style": lambda out: False})
    output = asyncio.run(
        engine.run(_FixedContentStrategy("content"), _make_input(policy=policy))
    )
    assert output.stop_reason == "completed"
    assert output.content == "content"


def test_guardrail_repair_once_is_repaired_by_strategy() -> None:
    """A repair_once violation lets the strategy fix its output before returning."""
    policy = default_reasoning_policy(guardrails=(GuardrailSpec("quality", "repair_once"),))
    engine = ReasoningEngine(
        guardrail_checks={"quality": lambda out: str(out).startswith("GOOD")},
    )
    output = asyncio.run(engine.run(_RepairStrategy(), _make_input(policy=policy)))
    assert output.stop_reason == "completed"
    assert output.content == "GOOD output"


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_resolves_latest_and_by_constraint() -> None:
    """The registry resolves the latest version and honors SemVer constraints."""
    registry = ReasoningStrategyRegistry()
    v1 = _FixedContentStrategy("v1")
    v1.id, v1.version = "autodev/reasoning-fixed", "1.0.0"  # type: ignore[misc]
    v12 = _FixedContentStrategy("v12")
    v12.id, v12.version = "autodev/reasoning-fixed", "1.2.0"  # type: ignore[misc]
    registry.register(v1)
    registry.register(v12)

    assert registry.resolve("autodev/reasoning-fixed").version == "1.2.0"
    assert registry.resolve("autodev/reasoning-fixed", ">=1.0 <1.2").version == "1.0.0"
    assert registry.get("autodev/reasoning-fixed", "1.0.0").version == "1.0.0"
    assert registry.versions("autodev/reasoning-fixed") == ("1.2.0", "1.0.0")


def test_registry_rejects_duplicate_and_incompatible() -> None:
    """Duplicate versions and host-incompatible strategies are rejected."""
    registry = ReasoningStrategyRegistry()
    registry.register(_EchoStrategy())
    try:
        registry.register(_EchoStrategy())
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("duplicate registration should raise")

    incompatible = _FixedContentStrategy("old")
    incompatible.id = "autodev/reasoning-old"  # type: ignore[misc]
    incompatible.host_api = ">=1.0 <2.0"  # type: ignore[misc]
    try:
        registry.register(incompatible)
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("host-incompatible registration should raise")


def test_host_compatibility_check() -> None:
    """The host-compatibility helper admits 2.x ranges and rejects older ones."""
    assert is_host_compatible(">=2.0 <3.0") is True
    assert is_host_compatible("*") is True
    assert is_host_compatible(">=1.0 <2.0") is False


# --------------------------------------------------------------------------
# Manifest / policy validation
# --------------------------------------------------------------------------


def test_strategy_manifest_validation() -> None:
    """A well-formed reasoning-strategy manifest validates; a bad id fails."""
    valid: dict[str, Any] = {
        "schemaVersion": "1",
        "kind": "ReasoningStrategy",
        "id": "autodev/reasoning-react",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "entrypoint": {"runtime": "python", "ref": "pkg.module:Strategy"},
    }
    assert validate_reasoning_strategy_manifest(valid).valid is True

    bad = dict(valid, id="Not A Valid Id")
    result = validate_reasoning_strategy_manifest(bad)
    assert result.valid is False
    assert result.errors


def test_policy_validation() -> None:
    """A well-formed reasoning policy validates; a bad on_exceed fails."""
    valid: dict[str, Any] = {
        "schemaVersion": 1,
        "id": "autodev/reasoning-policy-default",
        "version": "1.2.0",
        "hostApi": ">=2.0 <3.0",
        "selection": {"default": "autodev/reasoning-react"},
        "budget": {"tokens": 24000, "cost_usd": 0.75, "wall_clock_ms": 45000, "max_steps": 12},
    }
    assert validate_reasoning_policy(valid).valid is True

    bad = dict(valid, budget=dict(valid["budget"], on_exceed="explode"))
    result = validate_reasoning_policy(bad)
    assert result.valid is False
    assert result.errors


# --------------------------------------------------------------------------
# Published schemas
# --------------------------------------------------------------------------


def test_published_schemas_are_valid_json() -> None:
    """Both published JSON schemas parse and declare a $schema dialect."""
    for name in ("reasoning-strategy.schema.json", "reasoning-policy.schema.json"):
        document = json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))
        assert "$schema" in document
        assert document["type"] == "object"
