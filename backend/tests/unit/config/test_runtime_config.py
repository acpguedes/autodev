"""Tests for :class:`RuntimeConfigService` config path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config.runtime import RuntimeConfigService


def test_config_path_follows_project_root_not_launch_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``autodev.config.json`` resolves relative to AUTODEV_PROJECT_ROOT, not cwd."""
    monkeypatch.delenv("AUTODEV_CONFIG_PATH", raising=False)
    project_root = tmp_path / "project"
    project_root.mkdir()
    launch_dir = tmp_path / "launch-dir"
    launch_dir.mkdir()
    monkeypatch.setenv("AUTODEV_PROJECT_ROOT", str(project_root))
    monkeypatch.chdir(launch_dir)

    service = RuntimeConfigService()

    assert service.config_path == (project_root / "autodev.config.json").resolve()
