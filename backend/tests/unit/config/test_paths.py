"""Tests for :mod:`backend.config.paths` (E61-S1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import paths
from backend.config.settings import Settings


def test_autodev_home_defaults_to_dot_autodev_under_the_real_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTODEV_HOME", raising=False)

    assert paths.autodev_home() == Path.home() / ".autodev"


def test_autodev_home_follows_the_override_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom-home"
    monkeypatch.setenv("AUTODEV_HOME", str(override))

    assert paths.autodev_home() == override


@pytest.mark.parametrize(
    "resolver",
    [paths.autodev_home, paths.global_config_path, paths.global_data_dir, paths.global_state_db_path],
)
def test_global_paths_do_not_move_with_the_working_directory(
    resolver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("AUTODEV_HOME", str(home))

    before = resolver()
    launch_dir = tmp_path / "launch-dir"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    after = resolver()

    assert before == after


def test_global_config_and_state_db_paths_resolve_under_the_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("AUTODEV_HOME", str(home))

    assert paths.global_config_path() == home / "autodev.config.json"
    assert paths.global_data_dir() == home / "data"
    assert paths.global_state_db_path() == home / "data" / "autodev.db"


def test_ensure_autodev_home_creates_the_home_and_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("AUTODEV_HOME", str(home))
    assert not home.exists()

    result = paths.ensure_autodev_home()

    assert result == home
    assert home.is_dir()
    assert (home / "data").is_dir()


def test_explicit_database_url_still_wins_over_the_new_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicitly configured DATABASE_URL is untouched by E61-S1-T2."""
    monkeypatch.setenv("AUTODEV_HOME", str(tmp_path / "home"))
    explicit_url = f"sqlite:///{tmp_path / 'explicit.db'}"
    monkeypatch.setenv("DATABASE_URL", explicit_url)

    assert Settings().database_url == explicit_url


def test_default_database_url_resolves_under_the_global_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no DATABASE_URL set, the default resolves under AUTODEV_HOME, not cwd."""
    home = tmp_path / "home"
    monkeypatch.setenv("AUTODEV_HOME", str(home))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    launch_dir = tmp_path / "launch-dir"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)

    settings = Settings(autodev_profile="local")

    assert settings.database_url == f"sqlite:///{home / 'data' / 'autodev.db'}"
