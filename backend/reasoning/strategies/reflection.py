"""Reflection / self-critique reasoning strategy (E4-S3).

Produces a draft, critiques it against the task, and revises — for a bounded
number of revisions or until the critique reports no issues. Each step is
mediated and budget-checked. See ``docs/architecture/v2_platform_reference.md``
§8.2.
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

_EXECUTE = "Produce a first draft answer for the task."
_CRITIQUE = "Critique the draft. If it is correct and complete, reply 'LGTM, no issues'."
_REVISE = "Revise the draft to address the critique."

_OK_MARKERS = ("no issues", "looks good", "lgtm", "approved", "no changes")


class ReflectionStrategy:
    """Reflection strategy: draft, self-critique, and revise within a bound."""

    id = "autodev/reasoning-reflection"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def __init__(self, *, max_revisions: int = 1) -> None:
        """Initialize the strategy.

        Args:
            max_revisions: Maximum critique/revise cycles to perform.
        """
        self._max_revisions = max_revisions

    def config_schema(self) -> dict[str, Any]:
        """Return the JSON Schema for this strategy's configuration."""
        return {
            "type": "object",
            "properties": {"max_revisions": {"type": "integer", "minimum": 0}},
            "additionalProperties": False,
        }

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Draft, critique, and revise the answer within the revision bound.

        Args:
            input: Immutable run input.
            ctx: Mediator for LLM/tool calls, budget, guardrails, and traces.

        Returns:
            The final revised :class:`ReasoningOutput` (``stop_reason="completed"``).
        """
        await ctx.check_budget()
        draft = str((await ctx.call_llm(
            [{"role": "system", "content": _EXECUTE}, {"role": "user", "content": input.task}]
        )).content)

        for revision in range(self._max_revisions):
            await ctx.check_budget()
            critique = str((await ctx.call_llm(
                [{"role": "system", "content": _CRITIQUE}, {"role": "user", "content": draft}]
            )).content)
            approved = _is_approved(critique)
            ctx.emit(
                TraceEvent(
                    sequence=0,
                    name="reasoning.reflection.critique",
                    payload={"revision": revision, "approved": approved},
                    timestamp=0.0,
                )
            )
            if approved:
                break
            draft = str((await ctx.call_llm(
                [
                    {"role": "system", "content": _REVISE},
                    {"role": "user", "content": f"Draft:\n{draft}\nCritique:\n{critique}"},
                ]
            )).content)
        return ReasoningOutput(content=draft, stop_reason="completed", usage=Usage(), trace_id="")


def _is_approved(critique: str) -> bool:
    """Return whether a critique indicates the draft needs no further revision.

    Args:
        critique: The critique text.

    Returns:
        ``True`` if the critique contains an approval marker.
    """
    lowered = critique.lower()
    return any(marker in lowered for marker in _OK_MARKERS)


__all__ = ["ReflectionStrategy"]
