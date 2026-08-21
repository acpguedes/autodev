"""Regression tests for E41-S1: structured LLM output reaching metadata.

Before this fix, every ``LangChainAgent`` subclass with a ``metadata_model()``
either overrode ``build_metadata()`` to unconditionally echo
``fallback_result()``'s hardcoded metadata, or inherited a base default that
did the same — regardless of whether the real LLM call succeeded. These
tests prove a successful call's structured output is what is persisted, for
a representative sample of both previously-overridden (planner, docs) and
inherited-default (coder) agents, plus that agents without a
``metadata_model()`` and the stub-provider path are unaffected.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from backend.agents.base import AgentContext
from backend.agents.contracts import CoderOutput, PlannerOutput
from backend.agents.contracts_ext import DocsOutput
from backend.agents.coder.agent import CoderAgent
from backend.agents.docs.agent import DocsAgent
from backend.agents.planner.agent import PlannerAgent


class _FakeStructuredRunnable:
    """Stands in for the runnable returned by ``with_structured_output``."""

    def __init__(self, instance: Any | None, *, error: bool = False) -> None:
        self._instance = instance
        self._error = error

    def invoke(self, messages: Any) -> Any:
        if self._error:
            raise NotImplementedError("structured output not supported")
        return self._instance


class _FakeChatModel(BaseChatModel):
    """Deterministic real-provider stand-in with a scriptable structured call."""

    is_stub: bool = False
    text: str = "on-topic generated content"
    structured_instance: Any = None
    structured_error: bool = False

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> _FakeStructuredRunnable:
        return _FakeStructuredRunnable(self.structured_instance, error=self.structured_error)


def _context() -> AgentContext:
    return AgentContext(session_id="s1", goal="Build a payment API", user_request="build it")


def test_planner_run_uses_real_structured_output_not_fallback() -> None:
    real_steps = ["Design the payment schema", "Wire the charge endpoint"]
    model = _FakeChatModel(structured_instance=PlannerOutput(steps=real_steps))
    agent = PlannerAgent(model=model)

    result = agent.run(_context())

    assert result.metadata["steps"] == real_steps
    fallback_steps = agent.fallback_result(_context()).metadata["steps"]
    assert result.metadata["steps"] != fallback_steps


def test_coder_run_uses_real_structured_output_not_fallback() -> None:
    real_output = CoderOutput(
        coding_tasks=[{"component": "backend/payments", "task": "Add charge endpoint"}]
    )
    model = _FakeChatModel(structured_instance=real_output)
    agent = CoderAgent(model=model)

    result = agent.run(_context())

    assert result.metadata["coding_tasks"] == [
        {"component": "backend/payments", "task": "Add charge endpoint"}
    ]
    fallback_tasks = agent.fallback_result(_context()).metadata["coding_tasks"]
    assert result.metadata["coding_tasks"] != fallback_tasks


def test_docs_run_uses_real_structured_output_not_fallback() -> None:
    real_output = DocsOutput(
        documents=["docs/payments.md"], sections=["Overview"], summary="Real summary"
    )
    model = _FakeChatModel(structured_instance=real_output)
    agent = DocsAgent(model=model)

    result = agent.run(_context())

    assert result.metadata["documents"] == ["docs/payments.md"]
    assert result.metadata["summary"] == "Real summary"


def test_structured_output_unsupported_falls_back_to_build_metadata() -> None:
    model = _FakeChatModel(text='{"steps": ["parsed from text"]}', structured_error=True)
    agent = PlannerAgent(model=model)

    result = agent.run(_context())

    assert result.metadata["steps"] == ["parsed from text"]


def test_structured_output_unsupported_and_unparseable_falls_back_to_fallback_metadata() -> None:
    model = _FakeChatModel(text="not json at all", structured_error=True)
    agent = PlannerAgent(model=model)

    result = agent.run(_context())

    assert result.metadata["steps"] == agent.fallback_result(_context()).metadata["steps"]


def test_stub_model_agent_never_reaches_structured_output_call() -> None:
    agent = PlannerAgent()  # no model given -> get_chat_model() -> StubChatModel

    result = agent.run(_context())

    assert result.metadata["steps"] == agent.fallback_result(_context()).metadata["steps"]
