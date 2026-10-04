"""E63-S2 tests: deterministic project-state probe."""

from __future__ import annotations

from pathlib import Path

from backend.projects import state as state_mod
from backend.projects.state import (
    cached_project_state,
    clear_state_cache,
    probe_project_state,
)


def test_empty_directory(tmp_path: Path) -> None:
    result = probe_project_state(tmp_path)
    assert not result.populated and not result.git and not result.tests


def test_lone_git_dir_is_empty_but_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = probe_project_state(tmp_path)
    assert result.git and not result.populated


def test_populated_without_git(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n")
    result = probe_project_state(tmp_path)
    assert result.populated and not result.git and not result.tests
    assert result.languages == ("python",)


def test_populated_git_and_tests(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("export {}\n")
    (tmp_path / "tests").mkdir()
    result = probe_project_state(tmp_path)
    assert result.populated and result.git and result.tests
    assert result.languages == ("typescript",)


def test_never_descends_into_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "test_x.py").write_text("")
    result = probe_project_state(tmp_path)
    assert not result.tests and result.languages == ()


def test_context_digest_projection(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / "test_a.py").write_text("")
    digest = probe_project_state(tmp_path).to_context_digest("repo-1")
    assert digest.signals.has_tests and digest.signals.languages == ("python",)


def test_cache_hits_and_invalidates(tmp_path: Path, monkeypatch) -> None:
    clear_state_cache()
    calls: list[Path] = []
    real = state_mod.probe_project_state

    def counting(root):  # type: ignore[no-untyped-def]
        calls.append(Path(root))
        return real(root)

    monkeypatch.setattr(state_mod, "probe_project_state", counting)
    assert not cached_project_state(tmp_path).populated
    cached_project_state(tmp_path)
    assert len(calls) == 1
    (tmp_path / "new.py").write_text("")
    import os, time

    future = time.time() + 5
    os.utime(tmp_path, (future, future))
    assert cached_project_state(tmp_path).populated
    assert len(calls) == 2
