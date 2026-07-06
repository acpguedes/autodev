"""Reference LLM-assisted skill: summarize a prompt via the LLM provider abstraction.

Uses :class:`backend.agents.provider.StubLLMProvider` so the skill runs fully
offline by default, matching the sandbox's no-network-by-default posture.
"""

from __future__ import annotations

from typing import Any

from backend.agents.provider import LLMProvider, StubLLMProvider

_DEFAULT_PROVIDER: LLMProvider = StubLLMProvider(text="stub summary")


def run(prompt: str, *, provider: LLMProvider | None = None) -> dict[str, Any]:
    """Summarize a prompt via the configured LLM provider.

    Args:
        prompt: Text to summarize.
        provider: Provider to use; defaults to the offline stub.

    Returns:
        A dict with the ``summary`` text.
    """
    response = (provider or _DEFAULT_PROVIDER).complete(
        prompt, agent_id="autodev/skill-summarize-llm", run_id="skill-invocation", tenant_id="default"
    )
    return {"summary": response.text}


def register() -> None:
    """Plugin entrypoint hook; this skill has no extra registration side effects."""
    return None


__all__ = ["register", "run"]
