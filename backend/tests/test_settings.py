"""Tests for the E0 typed declarative settings layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.config.settings import Settings, reset_settings_cache


@pytest.fixture(autouse=True)
def clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AUTODEV_PROFILE",
        "AUTODEV_SETTINGS_FILE",
        "DATABASE_URL",
        "LLM_PROVIDER",
        "OPENAI_API_KEY",
        "AUTODEV_REDIS_URL",
        "AUTODEV_MINIO_ENDPOINT",
        "AUTODEV_MINIO_ACCESS_KEY",
        "AUTODEV_MINIO_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_settings_cache()


def test_local_profile_defaults_to_sqlite_and_stub_provider() -> None:
    settings = Settings()

    assert settings.autodev_profile == "local"
    assert settings.database_url.startswith("sqlite:///")
    assert settings.llm_provider == "stub"
    assert settings.storage_backend == "local"


def test_prod_profile_requires_postgres_redis_and_minio() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(autodev_profile="prod")

    message = str(excinfo.value)
    assert "prod profile requires DATABASE_URL to use PostgreSQL" in message
    assert "prod profile requires AUTODEV_REDIS_URL" in message
    assert "prod profile requires MinIO/S3 settings" in message


def test_settings_file_loads_below_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "llm_provider": "ollama",
                "openai_model": "llama3.1",
                "database_url": "sqlite:////tmp/from-file.db",
            }
        )
    )

    monkeypatch.setenv("AUTODEV_SETTINGS_FILE", str(settings_file))
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    settings = Settings()

    assert settings.llm_provider == "ollama"
    assert settings.openai_model == "env-model"
    assert settings.database_url == "sqlite:////tmp/from-file.db"


def test_redacted_dump_never_exposes_secret_values() -> None:
    settings = Settings(
        openai_api_key="sk-test",
        autodev_api_token="token-test",
        autodev_minio_secret_key="minio-secret",
    )

    redacted = settings.redacted_model_dump()

    assert redacted["openai_api_key"] == "***"
    assert redacted["autodev_api_token"] == "***"
    assert redacted["autodev_minio_secret_key"] == "***"
