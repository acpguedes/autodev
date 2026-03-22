"""Analyzer agent that interprets repository state and user intent."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts import AnalyzerOutput


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

    def metadata_model(self):
        return AnalyzerOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        impacted_areas = [
            "backend orchestrator",
            "runtime configuration",
            "repository intelligence",
        ]
        risks = [
            "Machine-readable outputs are still lightly typed in several agents",
            "UI rendering cannot yet rely on published agent contracts",
        ]
        next_actions = [
            "Add typed metadata contracts for every agent result",
            "Publish contract schemas through the API for UI consumption",
            "Extend tests to cover metadata validation and regressions",
        ]
        summary = (
            "Analyzer Agent evaluated the request and recommends finishing the "
            "structured-output slice so downstream workflows can depend on "
            "validated machine-readable artifacts."
        )
        metadata = {
            "summary": summary,
            "impacted_areas": impacted_areas,
            "risks": risks,
            "next_actions": next_actions,
        }
        return AgentResult(content=summary, metadata=metadata)


__all__ = ["AnalyzerAgent"]
