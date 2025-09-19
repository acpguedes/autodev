"""Core abstractions shared by all AutoDev agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

from backend.llm import LLMConfigurationError, get_chat_model, is_configured_model


@dataclass(slots=True)
class AgentContext:
    """Lightweight container with execution context for an agent."""

    session_id: str
    goal: str | None = None
    history: List[Dict[str, str]] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)

    def with_artifact(self, key: str, value: Any) -> "AgentContext":
        """Return a new context that includes an extra artifact."""

        updated = dict(self.artifacts)
        updated[key] = value
        return AgentContext(
            session_id=self.session_id,
            goal=self.goal,
            history=list(self.history),
            artifacts=updated,
        )

    def with_message(self, role: str, content: str) -> "AgentContext":
        """Return a new context with an appended history entry."""

        history = list(self.history)
        history.append({"role": role, "content": content})
        return AgentContext(
            session_id=self.session_id,
            goal=self.goal,
            history=history,
            artifacts=dict(self.artifacts),
        )


@dataclass(slots=True)
class AgentResult:
    """Output produced by an agent execution."""

    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    """Protocol implemented by all concrete agents."""

    name: str

    def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent with the provided context."""


class LangChainAgent(ABC):
    """Base class for agents that rely on LangChain prompts."""

    name: str

    def __init__(self, model: BaseChatModel | None = None) -> None:
        self._model = model or get_chat_model()
        self._prompt = self.build_prompt()

    @property
    def prompt(self) -> ChatPromptTemplate:
        """Return the prompt template associated with this agent."""

        return self._prompt

    @abstractmethod
    def build_prompt(self) -> ChatPromptTemplate:
        """Return the chat prompt for this agent."""

    def prepare_inputs(self, context: AgentContext) -> Dict[str, Any]:
        """Provide template variables for the chat prompt."""

        return {
            "goal": context.goal or "",
            "history": self._render_history(context.history),
            "artifacts": self._render_artifacts(context.artifacts),
        }

    @abstractmethod
    def fallback_result(self, context: AgentContext) -> AgentResult:
        """Return a deterministic result used when no LLM is available."""

    def build_metadata(
        self,
        context: AgentContext,
        fallback: AgentResult,
        generated_text: str,
    ) -> Mapping[str, Any]:
        """Derive metadata for the agent execution."""

        return fallback.metadata

    def run(self, context: AgentContext) -> AgentResult:
        fallback = self.fallback_result(context)

        if not is_configured_model(self._model):
            return fallback

        try:
            prompt_value = self.prompt.format_prompt(**self.prepare_inputs(context))
            response = self._model.invoke(prompt_value.to_messages())
        except LLMConfigurationError:
            return fallback
        except Exception:  # pragma: no cover - network or provider errors
            return fallback

        content = self._extract_content(response)
        metadata = self.build_metadata(context, fallback, content)
        return AgentResult(content=content, metadata=metadata)

    def _render_history(self, history: Iterable[Dict[str, str]]) -> str:
        lines = [f"{entry.get('role', 'unknown')}: {entry.get('content', '')}" for entry in history]
        return "\n".join(lines) if lines else "(no prior conversation)"

    def _render_artifacts(self, artifacts: Mapping[str, Any]) -> str:
        if not artifacts:
            return "(no artifacts)"
        pairs = [f"{name}: {value}" for name, value in artifacts.items()]
        return "\n".join(pairs)

    def _extract_content(self, response: Any) -> str:
        if isinstance(response, BaseMessage):
            return str(response.content)
        if isinstance(response, str):
            return response
        if hasattr(response, "content"):
            return str(response.content)
        return str(response)


__all__ = ["Agent", "AgentContext", "AgentResult", "LangChainAgent"]
