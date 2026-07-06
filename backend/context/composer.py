"""Context Provider composition (E7-S4-T2).

Runs multiple :class:`~backend.context.provider.ContextProvider`\\ s under
isolation — one provider raising or exceeding its timeout must never abort
the others or the calling agent run — and composes their outputs into one
ordered, deduplicated, weighted list.
"""

from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.context.provider import ContextItem, ContextProvider

logger = logging.getLogger(__name__)

#: Default per-provider timeout, in seconds.
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Per-provider composition policy.

    Attributes:
        provider: The context provider instance to run.
        weight: Multiplier applied to every item's score from this provider,
            letting a flow/policy prioritize one source over another
            (order/weight configurable per E7-S4's contract).
        timeout_seconds: Maximum time to wait for this provider before
            treating it as failed (isolated — does not abort the run).
    """

    provider: ContextProvider
    weight: float = 1.0
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class ComposedContext:
    """The composer's output: ordered, deduplicated, attributed context items.

    Attributes:
        items: Context items ordered by descending weighted score.
        failed_providers: ``provider_id -> error message`` for any provider
            that raised or timed out; the run continues without their
            context (see :meth:`ContextComposer.compose`).
    """

    items: list[ContextItem]
    failed_providers: dict[str, str] = field(default_factory=dict)


class ContextComposer:
    """Runs and composes multiple context providers under isolation."""

    def __init__(self, configs: list[ProviderConfig]) -> None:
        """Initialize the composer with an ordered list of provider configs.

        Args:
            configs: Providers to run, each with its own weight/timeout. List
                order has no effect on the output order (items are always
                sorted by score) but is preserved for readability/debugging.
        """
        self._configs = configs

    def compose(self, query: str, *, limit: int | None = None, **kwargs: Any) -> ComposedContext:
        """Run every configured provider and compose their results.

        Each provider runs concurrently in a bounded thread pool with its own
        timeout; a provider that raises or exceeds its timeout is recorded in
        ``failed_providers`` and contributes no items — it never raises out
        of this method or blocks the other providers' results.

        Args:
            query: Forwarded to every provider's ``get_context``.
            limit: Optional cap on the number of items returned, applied
                after ordering (keeps only the highest-scoring items).
            **kwargs: Forwarded to every provider's ``get_context``.

        Returns:
            The composed, deduplicated, ordered context.
        """
        if not self._configs:
            return ComposedContext(items=[])

        items: list[ContextItem] = []
        failed: dict[str, str] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self._configs)) as executor:
            future_to_config = {
                executor.submit(config.provider.get_context, query, **kwargs): config
                for config in self._configs
            }
            for future, config in future_to_config.items():
                provider_id = getattr(config.provider, "provider_id", type(config.provider).__name__)
                try:
                    provider_items = future.result(timeout=config.timeout_seconds)
                except Exception as exc:  # noqa: BLE001 - isolate any provider failure/timeout
                    failed[provider_id] = str(exc)
                    logger.warning("Context provider %r failed or timed out: %s", provider_id, exc)
                    continue
                items.extend(
                    ContextItem(
                        content=item.content,
                        source=item.source,
                        score=item.score * config.weight,
                        metadata=item.metadata,
                    )
                    for item in provider_items
                )

        deduped = self._dedup(items)
        deduped.sort(key=lambda item: -item.score)
        if limit is not None:
            deduped = deduped[:limit]
        return ComposedContext(items=deduped, failed_providers=failed)

    def _dedup(self, items: list[ContextItem]) -> list[ContextItem]:
        """Remove items with identical content, keeping the highest-scoring instance."""
        best_by_content: dict[str, ContextItem] = {}
        for item in items:
            existing = best_by_content.get(item.content)
            if existing is None or item.score > existing.score:
                best_by_content[item.content] = item
        return list(best_by_content.values())


__all__ = ["ComposedContext", "ContextComposer", "DEFAULT_PROVIDER_TIMEOUT_SECONDS", "ProviderConfig"]
