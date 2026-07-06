"""Persisted session-memory ``ContextProvider`` (E7-S4-T4).

Reads prior messages for a session from the existing durable store
(:func:`backend.persistence.database.get_store`) and returns them as
attributable context items — the simplest "memory" a running agent can draw
on: what was already said earlier in this session.
"""

from __future__ import annotations

from typing import Any

from backend.context.provider import ContextItem
from backend.persistence.database import get_store

#: Default number of most-recent messages surfaced when a caller does not
#: configure a different limit.
DEFAULT_MAX_MESSAGES = 10


class SessionMemoryContextProvider:
    """Context provider surfacing a session's prior messages, most recent first."""

    provider_id = "session_memory"

    def __init__(self, store: Any | None = None, *, max_messages: int = DEFAULT_MAX_MESSAGES) -> None:
        """Initialize the provider.

        Args:
            store: Durable store to read messages from; defaults to the
                process-wide :func:`get_store` on first use.
            max_messages: Maximum number of most-recent messages to surface.
        """
        self._store = store
        self._max_messages = max_messages

    def get_context(self, query: str, *, session_id: str = "", **kwargs: Any) -> list[ContextItem]:
        """Return the session's most recent messages as context items.

        Args:
            query: Accepted for Protocol compatibility; unused — session
                memory in this slice surfaces recency-ordered recent history
                rather than query-filtered results.
            session_id: Session whose message history to read.
            **kwargs: Accepted for Protocol compatibility; ignored.

        Returns:
            One :class:`ContextItem` per recent message, most recent first,
            each attributed with session/sequence/role metadata; an empty
            list if ``session_id`` is empty or the session has no messages.
        """
        del query, kwargs
        if not session_id:
            return []
        store = self._store if self._store is not None else get_store()
        messages = store.list_messages(session_id)
        recent = messages[-self._max_messages :]
        return [
            ContextItem(
                content=f"{message['role']}: {message['content']}",
                source=self.provider_id,
                score=1.0,
                metadata={
                    "session_id": session_id,
                    "sequence": message["sequence"],
                    "role": message["role"],
                },
            )
            for message in reversed(recent)
        ]


__all__ = ["DEFAULT_MAX_MESSAGES", "SessionMemoryContextProvider"]
