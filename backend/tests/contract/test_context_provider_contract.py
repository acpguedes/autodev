"""Contract test for the ``context_provider`` extension point (E12-S2).

Asserts that the :class:`~backend.context.provider.ContextProvider`
runtime-checkable Protocol shape is stable, verified with both a minimal
ad hoc conforming object and the project's real
:class:`~backend.context.providers.session_memory.SessionMemoryContextProvider`
implementation.
"""

from __future__ import annotations

from backend.context.provider import ContextItem, ContextProvider
from backend.context.providers.session_memory import SessionMemoryContextProvider


class _StaticContextProvider:
    """Minimal object satisfying the ContextProvider structural Protocol."""

    provider_id = "static-probe"

    def get_context(self, query: str, **kwargs: object) -> list[ContextItem]:
        """Return a single fixed context item regardless of the query.

        Args:
            query: The context query (ignored).
            **kwargs: Additional provider-specific keyword arguments (ignored).

        Returns:
            A single-element list containing a fixed :class:`ContextItem`.
        """
        return [ContextItem(content=query, source=self.provider_id)]


def test_context_provider_protocol_is_runtime_checkable() -> None:
    """A minimal conforming object is recognized via isinstance()."""
    provider: ContextProvider = _StaticContextProvider()

    assert isinstance(provider, ContextProvider)

    items = provider.get_context("hello")

    assert items == [ContextItem(content="hello", source="static-probe")]


def test_session_memory_provider_conforms_to_the_contract() -> None:
    """The real SessionMemoryContextProvider implementation conforms too.

    Uses an empty ``session_id`` so the call short-circuits before touching
    any durable store, keeping this contract test deterministic and
    offline -- the goal here is Protocol conformance, not storage behavior.
    """
    provider = SessionMemoryContextProvider()

    assert isinstance(provider, ContextProvider)
    assert isinstance(provider.provider_id, str)

    items = provider.get_context("hello", session_id="")

    assert items == []
