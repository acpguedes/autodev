"""Analyzer agent that interprets repository state and user intent."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent


class AnalyzerAgent(LangChainAgent):
    """Summarise the delta required to fulfil the user's goal."""

    name = "analyzer"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Analyzer agent in the AutoDev collective. "
                    "Review the goal, conversation history and intermediate artifacts to "
                    "highlight the most impactful technical areas to investigate next.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "History so far:\n{history}\n"
                    "Shared artifacts:\n{artifacts}\n"
                    "Provide a concise summary of the situation and name the product areas "
                    "that deserve immediate attention.",
                ),
            ]
        )

    def fallback_result(self, context: AgentContext) -> AgentResult:
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
