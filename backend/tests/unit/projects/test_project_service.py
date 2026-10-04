"""E62-S4: open / initialize / create, and the additive-only invariant."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.persistence.sqlite_adapter import SQLiteStore
from backend.projects import ProjectConfigError, ProjectStore
from backend.projects.service import ProjectPathError, create_project, initialize_project, open_project


@pytest.fixture()
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(store=SQLiteStore(f"sqlite:///{tmp_path / 'p.db'}"))


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".autodev" not in p.relative_to(root).parts
    }


def test_initialize_in_place_changes_no_file_and_starts_no_run(tmp_path: Path, store: ProjectStore, monkeypatch) -> None:
    root = tmp_path / "existing"
    (root / "src").mkdir(parents=True)
    (root / "README.md").write_text("keep me\n")
    (root / ".gitignore").write_text("*.pyc\n")
    (root / "src" / "app.py").write_text("print(1)\n")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    before = _snapshot(root)
    entries_before = sorted(p.name for p in root.iterdir())

    runs: list[object] = []
    monkeypatch.setattr("backend.orchestrator.service.core.OrchestratorService.begin_message", lambda *a, **k: runs.append(1))
    monkeypatch.setattr("backend.jobs.queue.get_queue", lambda *a, **k: runs.append(1))

    record = initialize_project("t", root, store=store)

    assert _snapshot(root) == before  # every pre-existing file byte-identical
    assert sorted(p.name for p in root.iterdir()) == sorted([*entries_before, ".autodev"])
    assert sorted(p.name for p in (root / ".autodev").iterdir()) == ["config.json", "project.json"]
    assert runs == []
    assert record.is_active and record.name == "existing"
    assert '"branch": "main"' in (root / ".autodev" / "project.json").read_text()


def test_initialize_keeps_existing_autodev_files(tmp_path: Path, store: ProjectStore) -> None:
    root = tmp_path / "p"
    (root / ".autodev").mkdir(parents=True)
    (root / ".autodev" / "config.json").write_text('{"x": 1}')
    initialize_project("t", root, name="n", store=store)
    assert (root / ".autodev" / "config.json").read_text() == '{"x": 1}'


def test_gitless_directory_initializes(tmp_path: Path, store: ProjectStore) -> None:
    root = tmp_path / "nogit"
    root.mkdir()
    assert initialize_project("t", root, store=store).name == "nogit"


def test_open_requires_marker_and_valid_files(tmp_path: Path, store: ProjectStore) -> None:
    root = tmp_path / "p"
    root.mkdir()
    with pytest.raises(ProjectPathError):
        open_project("t", root, store=store)
    (root / ".autodev").mkdir()
    (root / ".autodev" / "project.json").write_text("{bad")
    with pytest.raises(ProjectConfigError):
        open_project("t", root, store=store)


def test_create_makes_directory_then_initializes_and_refuses_existing(tmp_path: Path, store: ProjectStore) -> None:
    root = tmp_path / "new" / "deep"
    record = create_project("t", root, name="fresh", store=store)
    assert (root / ".autodev" / "project.json").is_file() and record.name == "fresh"
    with pytest.raises(ProjectPathError):
        create_project("t", root, store=store)


def test_doctor_reports_discovered_project_and_depth(tmp_path: Path) -> None:
    from backend.ops.doctor import _check_discovered_project

    root = tmp_path / "p"
    (root / ".autodev").mkdir(parents=True)
    deep = root / "a" / "b"
    deep.mkdir(parents=True)
    ok = _check_discovered_project(deep)
    assert ok.status == "ok" and "2 level(s) above" in ok.detail and str(root.resolve()) in ok.detail
    (root / ".autodev" / "project.json").write_text("{bad")
    bad = _check_discovered_project(deep)
    assert bad.status == "fail" and "project.json" in bad.detail


def test_cli_project_subcommands_register_and_open_uses_discovery(tmp_path: Path, monkeypatch, capsys) -> None:
    from backend.cli import build_parser

    args = build_parser().parse_args(["project", "init", str(tmp_path), "--name", "n"])
    assert args.handler.__name__ == "_handle_init" and args.name == "n"

    from backend.cli_plugins import project as cli_project

    root = tmp_path / "proj"
    (root / ".autodev").mkdir(parents=True)
    sub = root / "x"
    sub.mkdir()
    monkeypatch.chdir(sub)
    calls: list[tuple] = []
    monkeypatch.setattr(cli_project, "_call", lambda a, m, p, b=None: calls.append((m, p, b)) or 0)
    args = build_parser().parse_args(["project", "open"])
    assert args.handler(args) == 0
    assert calls == [("POST", "/v2/projects/open", {"root": str(root.resolve())})]
