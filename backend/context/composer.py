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

from opentelemetry import context as otel_context

from backend.context.provider import ContextItem, ContextProvider
from backend.observability.tracing import (
    trace_context_composition,
    trace_context_provider,
)

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


def _provider_id(provider: ContextProvider) -> str:
    """Return a provider's reporting id, falling back to its class name.

    Args:
        provider: Provider whose identifier is needed.

    Returns:
        The provider's ``provider_id`` attribute when present, else its class name.
    """
    return getattr(provider, "provider_id", type(provider).__name__)


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

        with trace_context_composition(provider_count=len(self._configs)) as composition:
            # Captured before submitting so each worker's provider span parents
            # onto the composition span instead of starting a detached trace.
            parent_context = otel_context.get_current()

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(self._configs)
            ) as executor:
                future_to_config = {
                    executor.submit(
                        self._run_provider, config, parent_context, query, kwargs
                    ): config
                    for config in self._configs
                }
                for future, config in future_to_config.items():
                    provider_id = _provider_id(config.provider)
                    try:
                        provider_items = future.result(timeout=config.timeout_seconds)
                    except Exception as exc:  # noqa: BLE001 - isolate any provider failure/timeout
                        failed[provider_id] = str(exc)
                        logger.warning(
                            "Context provider %r failed or timed out: %s", provider_id, exc
                        )
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

            composition.item_count = len(deduped)
            composition.failed_provider_count = len(failed)

        return ComposedContext(items=deduped, failed_providers=failed)

    @staticmethod
    def _run_provider(
        config: ProviderConfig,
        parent_context: Any,
        query: str,
        kwargs: dict[str, Any],
    ) -> list[ContextItem]:
        """Run one provider inside its own span, parented onto the composition.

        Runs on a worker thread, where the ambient OpenTelemetry context is
        empty, so *parent_context* is attached for the duration of the call.
        The span therefore measures the provider's real execution time and
        stays accurate even when the composer stops waiting for it on timeout.

        Args:
            config: Provider configuration to execute.
            parent_context: OpenTelemetry context captured on the calling thread.
            query: Forwarded to the provider's ``get_context``.
            kwargs: Forwarded to the provider's ``get_context``.

        Returns:
            The provider's context items.
        """
        token = otel_context.attach(parent_context)
        try:
            with trace_context_provider(
                provider_id=_provider_id(config.provider),
                weight=config.weight,
            ) as measurements:
                provider_items = list(config.provider.get_context(query, **kwargs))
                measurements.item_count = len(provider_items)
                return provider_items
        finally:
            otel_context.detach(token)

    def _dedup(self, items: list[ContextItem]) -> list[ContextItem]:
        """Remove items with identical content, keeping the highest-scoring instance."""
        best_by_content: dict[str, ContextItem] = {}
        for item in items:
            existing = best_by_content.get(item.content)
            if existing is None or item.score > existing.score:
                best_by_content[item.content] = item
        return list(best_by_content.values())


__all__ = ["ComposedContext", "ContextComposer", "DEFAULT_PROVIDER_TIMEOUT_SECONDS", "ProviderConfig"]
