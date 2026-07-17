"""Tests for the E7-S4 ContextProvider extension point, composer, and AgentRuntime integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agents.manifest import AgentManifest, validate_agent_manifest
from backend.agents.runtime import AgentRuntime, AgentRuntimeContext
from backend.context.composer import ContextComposer, ProviderConfig
from backend.context.provider import ContextItem
from backend.context.providers.files import FilesContextProvider
from backend.context.providers.session_memory import SessionMemoryContextProvider
from backend.persistence.sqlite_adapter import SQLiteStore


class _RaisingProvider:
    """A ContextProvider that always raises, used to verify composer isolation."""

    provider_id = "raising"

    def get_context(self, query: str, **kwargs: Any) -> list[ContextItem]:  # noqa: ARG002
        raise RuntimeError("boom")


class _ConstantProvider:
    """A ContextProvider that always returns one fixed item, for weighting/dedup tests."""

    def __init__(self, provider_id: str, content: str, score: float = 1.0) -> None:
        self.provider_id = provider_id
        self._content = content
        self._score = score

    def get_context(self, query: str, **kwargs: Any) -> list[ContextItem]:  # noqa: ARG002
        return [ContextItem(content=self._content, source=self.provider_id, score=self._score)]


def _runtime_manifest() -> AgentManifest:
    """Build a valid agent manifest for runtime tests (mirrors test_agents_runtime.py)."""
    raw = {
        "schemaVersion": "2.0",
        "kind": "Agent",
        "id": "acme/context-agent",
        "version": "1.0.0",
        "hostApi": ">=2.0 <3.0",
        "capabilities": [{"id": "code.implementation", "version": "1.0.0"}],
        "io": {
            "contract": "acme/context-io",
            "contractVersion": "1.0.0",
            "input": {
                "type": "object",
                "additionalProperties": False,
                "required": ["schemaVersion", "task"],
                "properties": {
                    "schemaVersion": {"const": "1.0.0"},
                    "task": {"type": "string", "minLength": 1},
                },
            },
            "output": {
                "type": "object",
                "additionalProperties": False,
                "required": ["schemaVersion", "status", "result"],
                "properties": {
                    "schemaVersion": {"const": "1.0.0"},
                    "status": {"enum": ["ok", "error"]},
                    "result": {"type": "string"},
                },
            },
        },
        "policy": {},
        "budgets": {},
        "entrypoint": {"runtime": "python", "ref": "context_agent:Agent"},
    }
    result = validate_agent_manifest(raw)
    assert result.valid, result.errors
    assert result.manifest is not None
    return result.manifest


def _payload() -> dict[str, str]:
    """Build a minimal valid input payload matching the test manifest's input schema."""
    return {"schemaVersion": "1.0.0", "task": "implement"}


# ---------------------------------------------------------------------------
# ContextComposer: isolation, weighting, dedup, limit
# ---------------------------------------------------------------------------


def test_composer_isolates_a_raising_provider(tmp_path: Path) -> None:
    """One provider raising does not prevent the others' context from being composed."""
    file_path = tmp_path / "notes.py"
    file_path.write_text("def helper():\n    pass\n", encoding="utf-8")
    files_provider = FilesContextProvider([file_path])
    composer = ContextComposer(
        [ProviderConfig(provider=files_provider), ProviderConfig(provider=_RaisingProvider())]
    )

    composed = composer.compose("helper")

    assert len(composed.items) == 1
    assert composed.items[0].source == "files"
    assert "raising" in composed.failed_providers
    assert "boom" in composed.failed_providers["raising"]


def test_composer_no_providers_returns_empty_context() -> None:
    composed = ContextComposer([]).compose("anything")
    assert composed.items == []
    assert composed.failed_providers == {}


def test_composer_weight_reorders_by_priority() -> None:
    """A higher-weighted provider's item outranks a lower-weighted one with an equal base score."""
    composer = ContextComposer(
        [
            ProviderConfig(provider=_ConstantProvider("low", "low content", 1.0), weight=1.0),
            ProviderConfig(provider=_ConstantProvider("high", "high content", 1.0), weight=5.0),
        ]
    )

    composed = composer.compose("q")

    assert composed.items[0].source == "high"


def test_composer_dedups_identical_content_keeping_highest_score() -> None:
    composer = ContextComposer(
        [
            ProviderConfig(provider=_ConstantProvider("a", "same text", 1.0)),
            ProviderConfig(provider=_ConstantProvider("b", "same text", 2.0)),
        ]
    )

    composed = composer.compose("q")

    assert len(composed.items) == 1
    assert composed.items[0].source == "b"


def test_composer_limit_keeps_only_top_scoring_items() -> None:
    class _MultiProvider:
        provider_id = "multi"

        def get_context(self, query: str, **kwargs: Any) -> list[ContextItem]:  # noqa: ARG002
            return [ContextItem(content=f"item-{i}", source="multi", score=float(i)) for i in range(5)]

    composed = ContextComposer([ProviderConfig(provider=_MultiProvider())]).compose("q", limit=2)

    assert [item.content for item in composed.items] == ["item-4", "item-3"]


# ---------------------------------------------------------------------------
# SessionMemoryContextProvider
# ---------------------------------------------------------------------------


def test_session_memory_provider_reads_recent_messages_most_recent_first(tmp_path: Path) -> None:
    store = SQLiteStore(f"sqlite:///{tmp_path / 'memory.db'}")
    store.create_session(session_id="s1", goal="test goal", plan=[], artifacts={})
    store.append_messages(
        "s1", "r1", [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi there"}]
    )
    provider = SessionMemoryContextProvider(store=store)

    items = provider.get_context("", session_id="s1")

    assert [item.content for item in items] == ["assistant: hi there", "user: hello"]
    assert all(item.source == "session_memory" for item in items)


def test_session_memory_provider_without_session_id_returns_nothing() -> None:
    assert SessionMemoryContextProvider().get_context("q") == []


# ---------------------------------------------------------------------------
# AgentRuntime integration: composed context injected, failing provider isolated
# ---------------------------------------------------------------------------


def test_agent_runtime_injects_composed_context_and_isolates_failing_provider(tmp_path: Path) -> None:
    """A real files-based provider plus a deliberately-raising one: the run still completes."""
    file_path = tmp_path / "helper.py"
    file_path.write_text("def helper():\n    return 1\n", encoding="utf-8")
    composer = ContextComposer(
        [
            ProviderConfig(provider=FilesContextProvider([file_path])),
            ProviderConfig(provider=_RaisingProvider()),
        ]
    )
    runtime = AgentRuntime(context_composer=composer)
    manifest = _runtime_manifest()
    captured: dict[str, list[ContextItem]] = {}

    def handler(ctx: AgentRuntimeContext) -> dict[str, str]:
        captured["items"] = list(ctx.context_items)
        return {"schemaVersion": "1.0.0", "status": "ok", "result": "done"}

    result = runtime.run(manifest, _payload(), handler, context_query="helper")

    assert result.status == "completed"
    assert len(captured["items"]) == 1
    assert captured["items"][0].source == "files"
    assert "def helper" in captured["items"][0].content


def test_agent_runtime_without_composer_has_empty_context_items() -> None:
    """The runtime's context injection is opt-in — no composer means no context_items."""
    runtime = AgentRuntime()
    manifest = _runtime_manifest()

    def handler(ctx: AgentRuntimeContext) -> dict[str, str]:
        assert ctx.context_items == []
        return {"schemaVersion": "1.0.0", "status": "ok", "result": "done"}

    result = runtime.run(manifest, _payload(), handler)

    assert result.status == "completed"
