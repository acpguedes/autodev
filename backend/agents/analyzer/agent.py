"""Analyzer agent that interprets repository state and user intent."""

from __future__ import annotations

from backend.agents.base import AgentContext, AgentResult


class AnalyzerAgent:
    """Summarise the delta required to fulfill the goal."""

    name = "analyzer"

    def run(self, context: AgentContext) -> AgentResult:
        summary = (
            "Analyzer Agent evaluated the request and suggests focusing on backend,"
            " frontend, and infrastructure scaffolding to unblock subsequent work."
        )
        metadata = {
            "goal": context.goal,
            "history_count": len(context.history),
        }
        return AgentResult(content=summary, metadata=metadata)


__all__ = ["AnalyzerAgent"]
