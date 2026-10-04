"""E62-S1: project discovery and on-disk metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.projects import (
    ProjectConfigError,
    discover_project_root,
    find_project_marker,
    load_project_config,
    load_project_metadata,
)


def _project(root: Path) -> Path:
    (root / ".autodev").mkdir(parents=True)
    return root


def test_found_at_depth(tmp_path: Path) -> None:
    proj = _project(tmp_path / "proj")
    deep = proj / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert discover_project_root(deep) == proj.resolve()
    assert find_project_marker(deep) == (proj.resolve(), 3)


def test_nested_projects_resolve_to_nearest(tmp_path: Path) -> None:
    outer = _project(tmp_path / "outer")
    inner = _project(outer / "pkg" / "inner")
    (inner / "src").mkdir()
    assert discover_project_root(inner / "src") == inner.resolve()


def test_no_marker_returns_none(tmp_path: Path) -> None:
    # tmp_path ancestors could contain .autodev (e.g. a home dir); guard the assumption.
    if discover_project_root(tmp_path) is not None:
        pytest.skip("an ancestor of tmp_path is itself a project")
    assert discover_project_root(tmp_path) is None


def test_gitless_directory_is_a_project(tmp_path: Path) -> None:
    proj = _project(tmp_path / "nogit")
    (proj / ".autodev" / "project.json").write_text(json.dumps({"name": "nogit"}))
    meta = load_project_metadata(proj)
    assert meta is not None and meta.name == "nogit" and meta.git is None


def test_empty_config_is_valid(tmp_path: Path) -> None:
    proj = _project(tmp_path / "p")
    (proj / ".autodev" / "config.json").write_text("{}")
    assert load_project_config(proj).model_dump() == {}
    assert load_project_metadata(proj) is None


@pytest.mark.parametrize(
    ("filename", "loader", "content"),
    [
        ("config.json", load_project_config, "{not json"),
        ("config.json", load_project_config, "[]"),
        ("project.json", load_project_metadata, "{not json"),
        ("project.json", load_project_metadata, json.dumps({"name": ""})),
        ("project.json", load_project_metadata, json.dumps({"name": "x", "bogus": 1})),
    ],
)
def test_malformed_file_raises_with_its_own_path(tmp_path: Path, filename, loader, content) -> None:
    proj = _project(tmp_path / "p")
    target = proj / ".autodev" / filename
    target.write_text(content)
    with pytest.raises(ProjectConfigError) as exc:
        loader(proj)
    assert str(target) in str(exc.value)
    assert exc.value.path == target
