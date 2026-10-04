"""Tests for :class:`RuntimeConfigService` (path resolution + E61-S2 layering)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.config.runtime import ConfigFileError, RuntimeConfigService


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


def _service(tmp_path: Path, *, global_doc: dict | None = None, project_doc: dict | None = None) -> RuntimeConfigService:
    """Build a service over isolated global/project config files for a test."""
    global_path = tmp_path / "global" / "autodev.config.json"
    project_path = tmp_path / "project" / "autodev.config.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.parent.mkdir(parents=True, exist_ok=True)
    if global_doc is not None:
        global_path.write_text(json.dumps(global_doc))
    if project_doc is not None:
        project_path.write_text(json.dumps(project_doc))
    return RuntimeConfigService(
        config_path=project_path,
        default_project_root=tmp_path / "project",
        global_config_path=global_path,
    )


class TestLayeredPrecedence:
    """A project file overriding one field inherits every other field (E61-S2-T1)."""

    def test_project_overrides_one_llm_field_and_inherits_the_rest(self, tmp_path: Path) -> None:
        service = _service(
            tmp_path,
            global_doc={"llm": {"provider": "openai", "model": "gpt-4o", "base_url": "https://global.invalid"}},
            project_doc={"llm": {"model": "gpt-4o-mini"}},
        )

        config = service.load()

        assert config.llm.provider == "openai"  # inherited from the global layer
        assert config.llm.base_url == "https://global.invalid"  # inherited from the global layer
        assert config.llm.model == "gpt-4o-mini"  # overridden by the project layer

    def test_project_overrides_one_repository_field_and_inherits_the_rest(self, tmp_path: Path) -> None:
        service = _service(
            tmp_path,
            global_doc={"repository": {"repository_label": "Global Label", "default_goal": "Global goal"}},
            project_doc={"repository": {"repository_label": "Project Label"}},
        )

        config = service.load()

        assert config.repository.repository_label == "Project Label"
        assert config.repository.default_goal == "Global goal"

    def test_global_layer_alone_is_visible_with_no_project_file(self, tmp_path: Path) -> None:
        service = _service(tmp_path, global_doc={"llm": {"provider": "ollama"}}, project_doc=None)

        assert service.load().llm.provider == "ollama"

    def test_internal_defaults_apply_when_no_layer_sets_a_field(self, tmp_path: Path) -> None:
        service = _service(tmp_path, global_doc={"llm": {"provider": "openai"}}, project_doc={})

        config = service.load()

        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o-mini"  # RuntimeConfig's own default


class TestFalsyValuesSurvive:
    """``false``/``0``/``""`` set explicitly are preserved, never collapsed (E61-S2-T2)."""

    def test_empty_string_base_url_is_preserved_over_an_inherited_one(self, tmp_path: Path) -> None:
        service = _service(
            tmp_path,
            global_doc={"llm": {"base_url": "https://global.invalid"}},
            project_doc={"llm": {"base_url": ""}},
        )

        assert service.load().llm.base_url == ""

    def test_zero_temperature_is_preserved(self, tmp_path: Path) -> None:
        service = _service(tmp_path, global_doc=None, project_doc={"llm": {"temperature": 0}})

        assert service.load().llm.temperature == 0

    def test_empty_repository_label_is_preserved(self, tmp_path: Path) -> None:
        service = _service(tmp_path, global_doc=None, project_doc={"repository": {"repository_label": ""}})

        assert service.load().repository.repository_label == ""


class TestInvalidConfigFile:
    """An invalid configuration file raises, naming the path, never treated as absent (E61-S2-T3)."""

    def test_invalid_json_raises_with_the_offending_path(self, tmp_path: Path) -> None:
        project_path = tmp_path / "project" / "autodev.config.json"
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project_path.write_text("{not valid json")
        service = RuntimeConfigService(
            config_path=project_path,
            default_project_root=tmp_path / "project",
            global_config_path=tmp_path / "global" / "autodev.config.json",
        )

        with pytest.raises(ConfigFileError) as exc_info:
            service.load()

        assert str(project_path) in str(exc_info.value)

    def test_non_object_json_raises_with_the_offending_path(self, tmp_path: Path) -> None:
        global_path = tmp_path / "global" / "autodev.config.json"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("[1, 2, 3]")
        service = RuntimeConfigService(
            config_path=tmp_path / "project" / "autodev.config.json",
            default_project_root=tmp_path / "project",
            global_config_path=global_path,
        )

        with pytest.raises(ConfigFileError) as exc_info:
            service.load()

        assert str(global_path) in str(exc_info.value)


class TestSaveIsLayerScoped:
    """``save()`` never copies an inherited value -- credentials in particular -- into the project file (E61-S2-T4)."""

    def test_an_inherited_global_api_key_is_not_written_to_the_project_file(self, tmp_path: Path) -> None:
        service = _service(tmp_path, global_doc={"llm": {"api_key": "global-secret"}}, project_doc=None)
        config = service.load()
        assert config.llm.api_key == "global-secret"

        # Save the full, materialized config back (as every API caller does) with
        # only an unrelated field actually changed.
        updated = config.model_copy(
            update={"repository": config.repository.model_copy(update={"repository_label": "New Label"})}
        )
        service.save(updated)

        project_raw = json.loads(service.config_path.read_text())
        assert "api_key" not in project_raw.get("llm", {})
        # ...but the merged view still resolves the secret, from the global layer.
        assert service.load().llm.api_key == "global-secret"

    def test_a_project_specific_api_key_different_from_global_is_persisted(self, tmp_path: Path) -> None:
        service = _service(tmp_path, global_doc={"llm": {"api_key": "global-secret"}}, project_doc=None)
        config = service.load()
        updated = config.model_copy(update={"llm": config.llm.model_copy(update={"api_key": "project-secret"})})

        service.save(updated)

        project_raw = json.loads(service.config_path.read_text())
        assert project_raw["llm"]["api_key"] == "project-secret"
        assert service.load().llm.api_key == "project-secret"

    def test_save_writes_only_the_changed_field(self, tmp_path: Path) -> None:
        service = _service(tmp_path, global_doc=None, project_doc=None)
        config = service.load()
        updated = config.model_copy(update={"llm": config.llm.model_copy(update={"provider": "openai"})})

        service.save(updated)

        project_raw = json.loads(service.config_path.read_text())
        assert project_raw == {"llm": {"provider": "openai"}}

