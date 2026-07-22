"""Contract test for the LLM provider extension surface (E12-S2).

``provider`` is a cross-cutting extension surface (agents, reasoning, and
skills all inject an :class:`~backend.agents.provider.LLMProvider`) rather
than a catalog-registered :class:`~backend.plugins.catalog.ExtensionPointKind`,
so this module is not parametrized through
``test_extension_point_coverage.py``. It still asserts the same guarantee
as the other contract tests: the :class:`LLMProvider` structural Protocol
shape is stable, verified against both of the project's reference
implementations.
"""

from __future__ import annotations

from backend.agents.provider import (
    LLMProvider,
    LLMProviderResponse,
    ScriptedLLMProvider,
    StubLLMProvider,
)


def _assert_conforms(provider: LLMProvider) -> None:
    """Assert a provider satisfies the LLMProvider Protocol end-to-end.

    Args:
        provider: The provider instance to exercise.
    """
    response = provider.complete(
        "hello", agent_id="acme/agent-probe", run_id="run-1", tenant_id="tenant-1"
    )

    assert isinstance(response, LLMProviderResponse)
    assert isinstance(response.text, str)
    assert isinstance(response.tokens_input, int)
    assert isinstance(response.tokens_output, int)
    assert isinstance(response.cost_usd, float)


def test_stub_llm_provider_conforms_to_the_contract() -> None:
    """StubLLMProvider satisfies the LLMProvider structural Protocol."""
    _assert_conforms(StubLLMProvider(text="ok"))


def test_scripted_llm_provider_conforms_to_the_contract() -> None:
    """ScriptedLLMProvider satisfies the LLMProvider structural Protocol."""
    _assert_conforms(ScriptedLLMProvider(["first", "second"]))


def test_scripted_llm_provider_replays_its_script_in_order() -> None:
    """Each call to complete() advances through the scripted responses."""
    provider = ScriptedLLMProvider(["first", "second"])

    first = provider.complete("p", agent_id="a", run_id="r1", tenant_id="t")
    second = provider.complete("p", agent_id="a", run_id="r2", tenant_id="t")

    assert first.text == "first"
    assert second.text == "second"
