"""Native tool-calling reasoning strategy (E4-S2).

Delegates the tool-orchestration loop to the LLM provider's own function/tool
calling, keeping Engine overhead minimal for models that already orchestrate
tools well. In the offline/stub path this reduces to a single mediated
completion. See ``docs/architecture/v2_platform_reference.md`` §8.2.
"""

from __future__ import annotations

from typing import Any

from backend.reasoning.contract import (
    ReasoningContext,
    ReasoningInput,
    ReasoningOutput,
    TraceEvent,
    Usage,
)


class NativeToolsStrategy:
    """Native tool-calling strategy: one mediated call, provider drives tools."""

    id = "autodev/reasoning-native-tools"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def config_schema(self) -> dict[str, Any]:
        """Return the JSON Schema for this strategy's configuration."""
        return {"type": "object", "additionalProperties": False}

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Issue a single mediated completion and return it.

        Args:
            input: Immutable run input.
            ctx: Mediator for LLM/tool calls, budget, guardrails, and traces.

        Returns:
            The final :class:`ReasoningOutput` (``stop_reason="completed"``).
        """
        await ctx.check_budget()
        result = await ctx.call_llm([{"role": "user", "content": input.task}])
        ctx.emit(TraceEvent(sequence=0, name="reasoning.native.completed", payload={}, timestamp=0.0))
        return ReasoningOutput(content=result.content, stop_reason="completed", usage=Usage(), trace_id="")


__all__ = ["NativeToolsStrategy"]
