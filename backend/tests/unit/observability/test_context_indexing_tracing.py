"""Tests for indexing and context-composition spans (E7-S1 / E7-S4 DoD).

Both stories declared "traces emitted" in their Definition of Done but shipped
without spans; these tests are the evidence that closes that gap and pins the
span names, attributes, and parent/child shape against regressions.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from backend.context.composer import ContextComposer, ProviderConfig
from backend.context.provider import ContextItem
from backend.observability.tracing import configure_tracing
from backend.persistence.sqlite_adapter import SQLiteStore
from backend.repository import indexing

_PY_SAMPLE = """\
def add(a, b):
    return a + b
"""


class _StaticProvider:
    """Context provider returning a fixed item list."""

    def __init__(self, provider_id: str, items: list[ContextItem]) -> None:
        """Store the provider id and the items to return.

        Args:
            provider_id: Identifier reported on spans and attribution.
            items: Items returned from every ``get_context`` call.
        """
        self.provider_id = provider_id
        self._items = items

    def get_context(self, query: str, **kwargs: Any) -> list[ContextItem]:
        """Return the configured items, ignoring the query.

        Args:
            query: Unused.
            **kwargs: Unused.

        Returns:
            The configured context items.
        """
        return list(self._items)


class _FailingProvider:
    """Context provider that always raises."""

    provider_id = "failing"

    def get_context(self, query: str, **kwargs: Any) -> list[ContextItem]:
        """Raise to exercise the composer's provider isolation.

        Args:
            query: Unused.
            **kwargs: Unused.

        Raises:
            RuntimeError: Always, carrying a message that must not be spanned.
        """
        raise RuntimeError("backend dsn=postgres://user:secret@host/db unreachable")


def _spans_named(exporter: InMemorySpanExporter, name: str) -> list[Any]:
    """Return every finished span with *name*.

    Args:
        exporter: Exporter collecting the finished spans.
        name: Span name to filter on.

    Returns:
        The matching spans, in export order.
    """
    return [span for span in exporter.get_finished_spans() if span.name == name]


def test_index_emits_span_with_counts_and_no_paths(tmp_path: Path) -> None:
    """Indexing a repo emits index/reindex spans carrying counts, not paths."""
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text(_PY_SAMPLE, encoding="utf-8")
    store = SQLiteStore(f"sqlite:///{tmp_path / 'index.db'}")

    written = indexing.index(repo, store=store)

    index_spans = _spans_named(exporter, "autodev.repository.index")
    assert len(index_spans) == 1
    attributes = dict(index_spans[0].attributes or {})
    assert attributes["autodev.index.operation"] == "index"
    assert attributes["autodev.index.file_count"] == 1
    assert attributes["autodev.index.chunks_written"] == written
    assert attributes["autodev.tenant_id"]

    # Repository and file paths must never reach a span.
    serialized = repr(attributes)
    assert str(repo) not in serialized
    assert "mod.py" not in serialized

    # `index` delegates to `reindex`, which gets its own nested span.
    reindex_spans = _spans_named(exporter, "autodev.repository.reindex")
    assert len(reindex_spans) == 1
    assert reindex_spans[0].parent is not None
    assert reindex_spans[0].parent.span_id == index_spans[0].context.span_id


def test_reindex_span_counts_deleted_chunks(tmp_path: Path) -> None:
    """Reindexing a vanished file reports the chunk rows it removed."""
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)

    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "mod.py"
    source.write_text(_PY_SAMPLE, encoding="utf-8")
    store = SQLiteStore(f"sqlite:///{tmp_path / 'index.db'}")
    indexing.index(repo, store=store)

    source.unlink()
    indexing.reindex(["mod.py"], repo_root=repo, store=store)

    attributes = dict(_spans_named(exporter, "autodev.repository.reindex")[-1].attributes or {})
    assert attributes["autodev.index.chunks_deleted"] >= 1
    assert attributes["autodev.index.chunks_written"] == 0


def test_compose_emits_one_span_per_provider_under_a_composition_span() -> None:
    """Each provider gets a child span; the composition span totals the result."""
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)

    composer = ContextComposer(
        [
            ProviderConfig(
                provider=_StaticProvider("files", [ContextItem(content="a", source="files")]),
                weight=2.0,
            ),
            ProviderConfig(
                provider=_StaticProvider(
                    "memory", [ContextItem(content="b", source="memory")]
                ),
            ),
        ]
    )

    composed = composer.compose("query")

    assert len(composed.items) == 2
    composition_spans = _spans_named(exporter, "autodev.context.compose")
    assert len(composition_spans) == 1
    composition = dict(composition_spans[0].attributes or {})
    assert composition["autodev.context.provider_count"] == 2
    assert composition["autodev.context.item_count"] == 2
    assert composition["autodev.context.failed_provider_count"] == 0

    provider_spans = _spans_named(exporter, "autodev.context.provider")
    assert len(provider_spans) == 2
    # Providers run on worker threads; the captured context must still parent
    # them onto the composition span rather than starting detached traces.
    for span in provider_spans:
        assert span.parent is not None
        assert span.parent.span_id == composition_spans[0].context.span_id

    by_id = {
        dict(span.attributes or {})["autodev.context.provider_id"]: dict(span.attributes or {})
        for span in provider_spans
    }
    assert by_id["files"]["autodev.context.weight"] == 2.0
    assert by_id["files"]["autodev.context.item_count"] == 1
    assert by_id["memory"]["autodev.context.status"] == "ok"


def test_failing_provider_span_is_error_without_leaking_the_message() -> None:
    """A provider failure marks its span ERROR with the type, never the message."""
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)

    composer = ContextComposer(
        [
            ProviderConfig(
                provider=_StaticProvider("files", [ContextItem(content="a", source="files")])
            ),
            ProviderConfig(provider=_FailingProvider()),
        ]
    )

    composed = composer.compose("query")

    assert "failing" in composed.failed_providers
    assert len(composed.items) == 1

    failing = next(
        dict(span.attributes or {})
        for span in _spans_named(exporter, "autodev.context.provider")
        if dict(span.attributes or {})["autodev.context.provider_id"] == "failing"
    )
    assert failing["autodev.context.status"] == "error"
    assert failing["autodev.context.error_type"] == "RuntimeError"

    failing_span = next(
        span
        for span in _spans_named(exporter, "autodev.context.provider")
        if dict(span.attributes or {})["autodev.context.provider_id"] == "failing"
    )
    assert failing_span.status.status_code is StatusCode.ERROR
    # The provider's message embeds a DSN with a password; nothing on the span
    # -- attributes, status description, or events -- may carry it.
    assert "secret" not in repr(failing_span.attributes)
    assert "secret" not in (failing_span.status.description or "")
    assert failing_span.events == ()

    composition = dict(_spans_named(exporter, "autodev.context.compose")[0].attributes or {})
    assert composition["autodev.context.failed_provider_count"] == 1


def test_timed_out_provider_span_records_its_real_duration() -> None:
    """A provider the composer stopped waiting for still reports its own span.

    Also pins the composer's current shutdown behavior: ``compose`` isolates a
    slow provider from the *result* at ``timeout_seconds``, but the surrounding
    ``ThreadPoolExecutor`` context manager still joins the worker before
    returning, so the call itself does not return early. That is a real gap
    against the "never blocks" wording in ``ContextComposer.compose``'s
    docstring, recorded in ``phases/e7_context_rag.md``; the span duration is
    what makes it diagnosable in the first place.
    """
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)

    provider_slept = 0.2

    class _SlowProvider:
        """Provider that outlives its configured composition timeout."""

        provider_id = "slow"

        def get_context(self, query: str, **kwargs: Any) -> list[ContextItem]:
            """Sleep past the composition timeout, then return one item.

            Args:
                query: Unused.
                **kwargs: Unused.

            Returns:
                A single context item the composer will already have dropped.
            """
            threading.Event().wait(provider_slept)
            return [ContextItem(content="late", source="slow")]

    composer = ContextComposer(
        [ProviderConfig(provider=_SlowProvider(), timeout_seconds=0.01)]
    )

    composed = composer.compose("query")

    # The composer gave up on the provider's result...
    assert composed.items == []
    assert "slow" in composed.failed_providers

    # ...but the worker's own span closed with its true duration, which is what
    # makes the slow provider identifiable rather than an anonymous timeout.
    provider_spans = _spans_named(exporter, "autodev.context.provider")
    assert len(provider_spans) == 1
    span = provider_spans[0]
    assert dict(span.attributes or {})["autodev.context.provider_id"] == "slow"
    elapsed_seconds = (span.end_time - span.start_time) / 1_000_000_000
    assert elapsed_seconds >= provider_slept
