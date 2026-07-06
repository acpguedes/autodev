"""``ContextProvider`` extension point (E7-S4-T1).

Analogous to :class:`backend.repository.providers.RepositoryProvider`: a
small structural Protocol any context source (files, session memory, a
future plugin-provided source) implements to contribute attributable
context items to an agent run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ContextItem:
    """One piece of context contributed by a :class:`ContextProvider`, with attribution.

    Attributes:
        content: The context text itself (a code snippet, a summarized
            message, etc.) — what actually gets injected into an agent run.
        source: Identifier of the provider that produced this item (e.g.
            ``"files"``, ``"session_memory"``), used for dedup and for
            attributing the item back to its origin.
        score: Relevance/priority score; higher is more important. Providers
            with no notion of ranking should return ``1.0`` for every item.
        metadata: Free-form provider-specific attribution details (e.g. a
            file path, a session/message id) surfaced to callers without
            being interpreted by the composer itself.
    """

    content: str
    source: str
    score: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ContextProvider(Protocol):
    """Structural Protocol for context sources.

    Attributes:
        provider_id: Stable identifier for this provider, used for dedup,
            ordering/weighting, and attribution.
    """

    provider_id: str

    def get_context(self, query: str, **kwargs: Any) -> list[ContextItem]:
        """Return context items relevant to *query*.

        Args:
            query: The agent/flow's current task or question, used to focus
                what context is returned.
            **kwargs: Provider-specific extra parameters (e.g. ``tenant_id``,
                ``session_id``).

        Returns:
            Attributable context items; an empty list if nothing relevant is
            found.

        Raises:
            Exception: Implementations may raise on internal errors rather
                than silently fabricating context — :class:`ContextComposer`
                (``backend/context/composer.py``) isolates provider
                failures, so one provider raising never aborts the others or
                the calling agent run.
        """
        ...


__all__ = ["ContextItem", "ContextProvider"]
