"""Tests for provider routing in the chat model factory."""

from __future__ import annotations

import sys
import types

import pytest

from backend.llm.factory import DEFAULT_OLLAMA_BASE_URL, get_chat_model


def test_ollama_provider_uses_local_openai_compatible_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "langchain_openai", types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI))
    get_chat_model.cache_clear()

    model = get_chat_model(provider="ollama", model="llama3.1")

    assert isinstance(model, FakeChatOpenAI)
    assert calls[0]["base_url"] == DEFAULT_OLLAMA_BASE_URL
    assert calls[0]["api_key"] == "ollama"
    assert calls[0]["model"] == "llama3.1"


def test_openai_provider_without_key_falls_back_to_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_chat_model.cache_clear()

    model = get_chat_model(provider="openai")

    assert getattr(model, "is_stub", False) is True
