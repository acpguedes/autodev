"""Responder agent that compiles the final user-facing response."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.agents.base import AgentContext, AgentResult, LangChainAgent
from backend.agents.contracts import ResponderOutput


class ResponderAgent(LangChainAgent):
    """Compile upstream agent outputs into the final response for the user."""

    name = "responder"

    def build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Responder agent. Synthesize the outputs from the specialist "
                    "agents into the final response for the user. Keep the answer grounded in "
                    "the current user request, clearly distinguish recommendations from actions, "
                    "and when the user asked for modifications, describe the concrete changes to apply.",
                ),
                (
                    "human",
                    "Goal: {goal}\n"
                    "Current user request: {user_request}\n"
                    "Conversation so far:\n{history}\n"
                    "Specialist artifacts:\n{artifacts}\n"
                    "Produce the final user-facing response.",
                ),
            ]
        )

    def metadata_model(self):
        return ResponderOutput

    def fallback_result(self, context: AgentContext) -> AgentResult:
        request = (context.user_request or context.goal or "").strip()
        requested_application = any(
            keyword in request.lower()
            for keyword in ("aplique", "implemente", "modifique", "altere", "corrija", "apply", "implement")
        )
        analyzer = context.artifacts.get("analyzer", {})
        coder = context.artifacts.get("coder", {})
        validator = context.artifacts.get("validator", {})

        highlights = []
        if analyzer.get("summary"):
            highlights.append(analyzer["summary"])
        for item in coder.get("coding_tasks", [])[:3]:
            component = item.get("component", "component")
            task = item.get("task", "")
            highlights.append(f"{component}: {task}")
        validation_steps = list(validator.get("validation_steps", []))[:2]

        response_mode = "apply_changes" if requested_application else "answer"
        intro = (
            "Os agentes consolidaram um plano de mudança orientado à aplicação das modificações solicitadas."
            if requested_application
            else "Os agentes consolidaram a análise dentro do contexto pedido pelo usuário."
        )
        summary = request or (context.goal or "Summarize the current execution state")
        response_lines = [intro]
        if summary:
            response_lines.append(f"Solicitação atual: {summary}.")
        if highlights:
            response_lines.append("Principais pontos: " + " ".join(f"- {item}" for item in highlights))
        if validation_steps:
            response_lines.append(
                "Validação recomendada: " + " ".join(f"- {step}" for step in validation_steps)
            )

        metadata = {
            "response_mode": response_mode,
            "summary": summary,
            "applies_user_request": bool(request),
            "source_agents": [
                agent_name
                for agent_name in ("navigator", "analyzer", "architect", "coder", "devops", "validator")
                if context.artifacts.get(agent_name)
            ],
            "recommended_actions": highlights[:4] or validation_steps,
        }
        return AgentResult(content="\n".join(response_lines), metadata=metadata)


__all__ = ["ResponderAgent"]
