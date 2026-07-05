"""ReAct reasoning strategy (E4-S2).

Implements the classic ``Thought -> Action -> Observation`` loop: the model is
asked to either take an ``ACTION <tool> <args>`` (which the mediator dispatches
to a granted tool) or emit a ``FINAL <answer>``. The loop is bounded by the
strategy's ``max_iterations`` and, independently, by the Engine's fail-closed
budget. See ``docs/architecture/v2_platform_reference.md`` §8.2.
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

_REACT_SYSTEM = (
    "You are a ReAct agent. Reply with either 'ACTION <tool> <args>' to use a "
    "tool, or 'FINAL <answer>' when you can answer."
)


class ReActStrategy:
    """ReAct strategy: iterative reason-act-observe with tool calls."""

    id = "autodev/reasoning-react"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def __init__(self, *, max_iterations: int | None = None) -> None:
        """Initialize the strategy.

        Args:
            max_iterations: Maximum reason/act iterations; defaults to the run
                budget's ``max_steps`` when ``None``.
        """
        self._max_iterations = max_iterations

    def config_schema(self) -> dict[str, Any]:
        """Return the JSON Schema for this strategy's configuration."""
        return {
            "type": "object",
            "properties": {"max_iterations": {"type": "integer", "minimum": 1}},
            "additionalProperties": False,
        }

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Run the ReAct loop until a final answer, iteration cap, or budget end.

        Args:
            input: Immutable run input.
            ctx: Mediator for LLM/tool calls, budget, guardrails, and traces.

        Returns:
            The final :class:`ReasoningOutput` (``stop_reason="completed"``).
        """
        limit = self._max_iterations or input.budget.max_steps
        scratchpad: list[str] = []
        last = ""
        for iteration in range(limit):
            await ctx.check_budget()
            result = await ctx.call_llm(_messages(input.task, scratchpad))
            last = str(result.content)
            kind, primary, argument = _parse_react(last)
            ctx.emit(
                TraceEvent(
                    sequence=0,
                    name="reasoning.step.thought",
                    payload={"iteration": iteration, "kind": kind},
                    timestamp=0.0,
                )
            )
            if kind == "final":
                return ReasoningOutput(content=primary, stop_reason="completed", usage=Usage(), trace_id="")
            if kind == "action":
                observation = await ctx.call_tool(primary, {"input": argument})
                scratchpad.append(f"Action: {primary}({argument})")
                scratchpad.append(f"Observation: {observation.output}")
                continue
            return ReasoningOutput(content=last, stop_reason="completed", usage=Usage(), trace_id="")
        return ReasoningOutput(content=last, stop_reason="completed", usage=Usage(), trace_id="")


def _messages(task: str, scratchpad: list[str]) -> list[dict[str, Any]]:
    """Build the ReAct prompt messages from the task and running scratchpad.

    Args:
        task: The task description.
        scratchpad: Accumulated action/observation lines.

    Returns:
        Role-tagged messages for the mediated LLM call.
    """
    user = task if not scratchpad else task + "\n" + "\n".join(scratchpad)
    return [{"role": "system", "content": _REACT_SYSTEM}, {"role": "user", "content": user}]


def _parse_react(text: str) -> tuple[str, str, str]:
    """Parse an LLM completion into a ReAct step.

    Args:
        text: The raw completion text.

    Returns:
        A ``(kind, primary, argument)`` tuple where ``kind`` is ``"final"``
        (``primary`` is the answer), ``"action"`` (``primary`` is the tool name,
        ``argument`` its input), or ``"answer"`` (``primary`` is a direct answer).
    """
    stripped = text.strip()
    upper = stripped.upper()
    if upper.startswith("FINAL"):
        return "final", stripped[len("FINAL"):].lstrip(": ").strip(), ""
    if upper.startswith("ACTION"):
        body = stripped[len("ACTION"):].lstrip(": ").strip()
        parts = body.split(None, 1)
        tool = parts[0] if parts else ""
        argument = parts[1] if len(parts) > 1 else ""
        return "action", tool, argument
    return "answer", stripped, ""


__all__ = ["ReActStrategy"]
