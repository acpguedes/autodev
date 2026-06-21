"""Tests for U5 specialized agents (security, refactor, docs).

Assertions:
- Each agent instantiates and run() returns an AgentResult whose metadata
  validates against its Pydantic output model.
- discover_agents() includes security/refactor/docs once agent modules are imported.
- OrchestratorConfig().agent_order does NOT contain the three new agents.
- OrchestratorService still constructs and handle_message returns results for
  the 7 ordered agents when given a valid session.
"""

from __future__ import annotations

import uuid

import pytest

from backend.agents.base import AgentContext, AgentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context() -> AgentContext:
    return AgentContext(
        session_id="test-session",
        goal="Test the specialized agent",
        user_request="Run a quick check",
        history=[],
    )


# ---------------------------------------------------------------------------
# SecurityAgent
# ---------------------------------------------------------------------------


def test_security_agent_imports() -> None:
    from backend.agents.security.agent import SecurityAgent  # noqa: F401

    assert SecurityAgent.name == "security"


def test_security_agent_run_returns_valid_metadata() -> None:
    from backend.agents.contracts_ext import SecurityOutput
    from backend.agents.security.agent import SecurityAgent

    agent = SecurityAgent()
    ctx = _make_context()
    result: AgentResult = agent.run(ctx)
    assert isinstance(result, AgentResult)
    # Validate metadata against the Pydantic model — must not raise.
    model = SecurityOutput(**result.metadata)
    assert isinstance(model.findings, list)
    assert isinstance(model.recommendations, list)
    assert model.severity in {"info", "low", "medium", "high", "critical"}


# ---------------------------------------------------------------------------
# RefactorAgent
# ---------------------------------------------------------------------------


def test_refactor_agent_imports() -> None:
    from backend.agents.refactor.agent import RefactorAgent  # noqa: F401

    assert RefactorAgent.name == "refactor"


def test_refactor_agent_run_returns_valid_metadata() -> None:
    from backend.agents.contracts_ext import RefactorOutput
    from backend.agents.refactor.agent import RefactorAgent

    agent = RefactorAgent()
    ctx = _make_context()
    result: AgentResult = agent.run(ctx)
    assert isinstance(result, AgentResult)
    model = RefactorOutput(**result.metadata)
    assert isinstance(model.targets, list)
    assert isinstance(model.smells, list)
    assert isinstance(model.suggested_changes, list)


# ---------------------------------------------------------------------------
# DocsAgent
# ---------------------------------------------------------------------------


def test_docs_agent_imports() -> None:
    from backend.agents.docs.agent import DocsAgent  # noqa: F401

    assert DocsAgent.name == "docs"


def test_docs_agent_run_returns_valid_metadata() -> None:
    from backend.agents.contracts_ext import DocsOutput
    from backend.agents.docs.agent import DocsAgent

    agent = DocsAgent()
    ctx = _make_context()
    result: AgentResult = agent.run(ctx)
    assert isinstance(result, AgentResult)
    model = DocsOutput(**result.metadata)
    assert isinstance(model.documents, list)
    assert isinstance(model.sections, list)
    assert isinstance(model.summary, str)


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_discover_agents_includes_specialized() -> None:
    """After importing agent modules the registry must expose all three agents."""
    # Side-effect imports trigger self-registration.
    import backend.agents.docs.agent  # noqa: F401
    import backend.agents.refactor.agent  # noqa: F401
    import backend.agents.security.agent  # noqa: F401

    from backend.agents.registry import discover_agents

    found = discover_agents()
    assert "security" in found
    assert "refactor" in found
    assert "docs" in found


# ---------------------------------------------------------------------------
# OrchestratorConfig.agent_order must NOT include the new agents
# ---------------------------------------------------------------------------


def test_specialized_agents_not_in_agent_order() -> None:
    from backend.orchestrator.service import OrchestratorConfig

    order = list(OrchestratorConfig().agent_order)
    assert "security" not in order
    assert "refactor" not in order
    assert "docs" not in order


# ---------------------------------------------------------------------------
# OrchestratorService construction and normal handle_message still works
# ---------------------------------------------------------------------------


def test_orchestrator_service_constructs() -> None:
    from backend.orchestrator.service import OrchestratorService

    svc = OrchestratorService()
    assert svc is not None


def test_orchestrator_handle_message_returns_ordered_results() -> None:
    """Normal handle_message must still return one result per agent in order."""
    from backend.orchestrator.service import OrchestratorConfig, OrchestratorService

    svc = OrchestratorService()

    # Create a session so handle_message can proceed.
    session_id = f"test-u5-{uuid.uuid4().hex[:8]}"
    svc._store.create_session(
        session_id=session_id,
        goal="Test U5 integration",
        plan=[],
        artifacts={},
    )

    run = svc.handle_message(session_id=session_id, message="Hello from test")

    expected_order = list(OrchestratorConfig().agent_order)
    result_agents = [step.agent for step in run.steps]

    # All ordered agents must appear in order.
    ordered_in_results = [a for a in result_agents if a in expected_order]
    assert ordered_in_results == expected_order
