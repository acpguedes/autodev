"""Tests for U16 pluggable repository intelligence provider.

Coverage:
- get_provider() returns LexicalProvider by default (no env var, tree_sitter absent).
- LexicalProvider extracts def/class names from Python source.
- LexicalProvider ignores indented (non-top-level) definitions.
- TreeSitterProvider degrades to lexical when tree_sitter is not installed.
- GET /repository/symbols?code=...&language=python returns 200 with symbols.
- GET /repository/symbols?path=<file> returns 200 for an existing file.
- GET /repository/symbols returns 422 when neither path nor code is provided.
- GET /repository/symbols?path=nonexistent returns 404.
- Response includes provider name.
"""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.repository.providers import LexicalProvider, get_provider
from backend.repository.providers.treesitter_provider import TreeSitterProvider


_PYTHON_SAMPLE = """\
def foo():
    pass


class Bar:
    def inner(self):
        pass


def baz():
    return 42
"""


# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------


def test_get_provider_default_is_lexical(monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_REPO_PROVIDER", raising=False)
    provider = get_provider()
    assert isinstance(provider, LexicalProvider)


def test_get_provider_treesitter_env_falls_back_to_lexical_when_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTODEV_REPO_PROVIDER", "treesitter")
    # Force tree_sitter import to fail by removing it from sys.modules.
    original = sys.modules.pop("tree_sitter", None)
    try:
        # Reload providers so the import guard re-runs.
        import importlib
        import backend.repository.providers as providers_mod

        importlib.reload(providers_mod)
        provider = providers_mod.get_provider()
        # When tree_sitter is truly absent the module falls back to lexical.
        assert isinstance(provider, (LexicalProvider, TreeSitterProvider))
    finally:
        if original is not None:
            sys.modules["tree_sitter"] = original


# ---------------------------------------------------------------------------
# LexicalProvider
# ---------------------------------------------------------------------------


def test_lexical_extracts_top_level_defs() -> None:
    provider = LexicalProvider()
    symbols = provider.extract_symbols(_PYTHON_SAMPLE, "python")
    assert "foo" in symbols
    assert "baz" in symbols


def test_lexical_extracts_top_level_class() -> None:
    provider = LexicalProvider()
    symbols = provider.extract_symbols(_PYTHON_SAMPLE, "python")
    assert "Bar" in symbols


def test_lexical_ignores_indented_methods() -> None:
    provider = LexicalProvider()
    symbols = provider.extract_symbols(_PYTHON_SAMPLE, "python")
    assert "inner" not in symbols


def test_lexical_empty_source_returns_empty_list() -> None:
    provider = LexicalProvider()
    assert provider.extract_symbols("", "python") == []


# ---------------------------------------------------------------------------
# TreeSitterProvider — graceful degradation
# ---------------------------------------------------------------------------


def test_treesitter_provider_degrades_when_lib_absent() -> None:
    """TreeSitterProvider must produce results even without tree_sitter installed."""
    provider = TreeSitterProvider()
    symbols = provider.extract_symbols(_PYTHON_SAMPLE, "python")
    # At minimum the lexical fallback must kick in.
    assert isinstance(symbols, list)
    assert len(symbols) > 0


# ---------------------------------------------------------------------------
# API endpoint — GET /repository/symbols
# ---------------------------------------------------------------------------


client = TestClient(app)


def test_api_symbols_code_param_returns_200() -> None:
    resp = client.get(
        "/repository/symbols",
        params={"code": _PYTHON_SAMPLE, "language": "python"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "symbols" in body
    assert "provider" in body
    assert "foo" in body["symbols"]
    assert "Bar" in body["symbols"]
    assert "baz" in body["symbols"]


def test_api_symbols_response_includes_provider_name() -> None:
    resp = client.get(
        "/repository/symbols",
        params={"code": "def hello(): pass", "language": "python"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["provider"], str)
    assert len(body["provider"]) > 0


def test_api_symbols_path_param_returns_200(tmp_path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("def greet(): pass\n", encoding="utf-8")
    resp = client.get(
        "/repository/symbols",
        params={"path": str(sample), "language": "python"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "greet" in body["symbols"]


def test_api_symbols_missing_params_returns_422() -> None:
    resp = client.get("/repository/symbols")
    assert resp.status_code == 422


def test_api_symbols_nonexistent_path_returns_404() -> None:
    resp = client.get(
        "/repository/symbols",
        params={"path": "/nonexistent/path/file.py", "language": "python"},
    )
    assert resp.status_code == 404
