"""Debate / Tree-of-Thought reasoning strategy (E4-S3).

Expands multiple candidate thoughts per level, scores them, and keeps the top
``beam`` — exploring alternatives under a budget and converging on the best. The
fan-out is bounded by the strategy's ``branches``/``depth``/``beam`` and, fail
closed, by the Engine budget: every candidate expansion calls
``ctx.check_budget()`` first, so the run stops with ``budget_exhausted`` rather
than overspending. See ``docs/architecture/v2_platform_reference.md`` §8.2.
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

_EXPAND = "Propose one distinct next thought toward solving the task."


class TreeOfThoughtStrategy:
    """Tree-of-Thought strategy: branch, score, and converge under budget."""

    id = "autodev/reasoning-tot"
    version = "1.0.0"
    host_api = ">=2.0 <3.0"

    def __init__(self, *, branches: int = 3, beam: int = 1, depth: int = 1) -> None:
        """Initialize the strategy.

        Args:
            branches: Candidate thoughts expanded per frontier node per level.
            beam: Number of top candidates carried to the next level.
            depth: Number of expansion levels.
        """
        self._branches = branches
        self._beam = beam
        self._depth = depth

    def config_schema(self) -> dict[str, Any]:
        """Return the JSON Schema for this strategy's configuration."""
        return {
            "type": "object",
            "properties": {
                "branches": {"type": "integer", "minimum": 1},
                "beam": {"type": "integer", "minimum": 1},
                "depth": {"type": "integer", "minimum": 1},
            },
            "additionalProperties": False,
        }

    async def run(self, input: ReasoningInput, ctx: ReasoningContext) -> ReasoningOutput:
        """Expand, score, and prune candidate thoughts, returning the best.

        Args:
            input: Immutable run input.
            ctx: Mediator for LLM/tool calls, budget, guardrails, and traces.

        Returns:
            The best candidate as a :class:`ReasoningOutput` (``completed``).
        """
        frontier: list[str] = [input.task]
        for level in range(self._depth):
            candidates: list[str] = []
            for parent in frontier:
                for _ in range(self._branches):
                    await ctx.check_budget()
                    proposal = await ctx.call_llm(
                        [{"role": "system", "content": _EXPAND}, {"role": "user", "content": parent}]
                    )
                    candidates.append(str(proposal.content))
            ranked = sorted(candidates, key=_score, reverse=True)
            frontier = ranked[: self._beam] or frontier
            ctx.emit(
                TraceEvent(
                    sequence=0,
                    name="reasoning.tot.level",
                    payload={"level": level, "candidates": len(candidates), "kept": len(frontier)},
                    timestamp=0.0,
                )
            )
        return ReasoningOutput(content=frontier[0], stop_reason="completed", usage=Usage(), trace_id="")


def _score(thought: str) -> int:
    """Heuristic score for a candidate thought (longer/more specific wins).

    Args:
        thought: The candidate thought text.

    Returns:
        A non-negative score used to rank candidates.
    """
    return len(thought.strip())


__all__ = ["TreeOfThoughtStrategy"]
