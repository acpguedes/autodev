"""Plan-and-Execute reasoning strategy (E4-S2).

Generates an explicit plan (one step per line) with a first LLM call, then
executes each step with a subsequent call, aggregating the results. Bounded by
the strategy's ``max_steps`` and the Engine's fail-closed budget. See
``docs/architecture/v2_platform_reference.md`` §8.2.
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

_PLAN_SYSTEM = "Produce a short numbered plan, one step per line, to accomplish the task."
_EXEC_SYSTEM = "Execute the given plan step and report the result concisely."


class PlanExecuteStrategy:
    """Plan-and-Execute strategy: plan first, then execute each step."""

    id = "autodev/reasoning-plan-execute"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def __init__(self, *, max_steps: int | None = None) -> None:
        """Initialize the strategy.

        Args:
            max_steps: Maximum plan steps to execute; defaults to the run
                budget's ``max_steps`` when ``None``.
        """
        self._max_steps = max_steps

    def config_schema(self) -> dict[str, Any]:
        """Return the JSON Schema for this strategy's configuration."""
        return {
            "type": "object",
            "properties": {"max_steps": {"type": "integer", "minimum": 1}},
            "additionalProperties": False,
        }

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Plan the task, execute each step, and aggregate the results.

        Args:
            input: Immutable run input.
            ctx: Mediator for LLM/tool calls, budget, guardrails, and traces.

        Returns:
            The final :class:`ReasoningOutput` (``stop_reason="completed"``).
        """
        await ctx.check_budget()
        plan_result = await ctx.call_llm(
            [{"role": "system", "content": _PLAN_SYSTEM}, {"role": "user", "content": f"Task: {input.task}"}]
        )
        steps = _parse_plan(str(plan_result.content), fallback=input.task)
        ctx.emit(TraceEvent(sequence=0, name="reasoning.plan.created", payload={"steps": len(steps)}, timestamp=0.0))

        limit = self._max_steps or input.budget.max_steps
        outputs: list[str] = []
        for index, step in enumerate(steps[:limit]):
            await ctx.check_budget()
            result = await ctx.call_llm(
                [{"role": "system", "content": _EXEC_SYSTEM}, {"role": "user", "content": f"Step: {step}"}]
            )
            outputs.append(str(result.content))
            ctx.emit(
                TraceEvent(sequence=0, name="reasoning.plan.step", payload={"index": index}, timestamp=0.0)
            )
        content = "\n".join(outputs) if outputs else str(plan_result.content)
        return ReasoningOutput(content=content, stop_reason="completed", usage=Usage(), trace_id="")


def _parse_plan(text: str, *, fallback: str) -> list[str]:
    """Split a plan completion into individual step strings.

    Args:
        text: The raw plan completion.
        fallback: A step to use when the completion contains no lines.

    Returns:
        A non-empty list of step strings.
    """
    steps = [line.strip(" -*\t0123456789.") for line in text.splitlines() if line.strip()]
    steps = [step for step in steps if step]
    return steps or [text.strip() or fallback]


__all__ = ["PlanExecuteStrategy"]
