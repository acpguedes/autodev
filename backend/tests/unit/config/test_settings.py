"""Tests for the E0 typed declarative settings layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.config.settings import Settings, reset_settings_cache


@pytest.fixture(autouse=True)
def clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear settings-related env vars and reset the settings cache before each test."""
    for name in (
        "AUTODEV_PROFILE",
        "AUTODEV_SETTINGS_FILE",
        "DATABASE_URL",
        "LLM_PROVIDER",
        "OPENAI_API_KEY",
        "AUTODEV_REDIS_URL",
        "AUTODEV_JOB_BACKEND",
        "AUTODEV_EVENT_BUS",
        "STORAGE_BACKEND",
        "AUTODEV_MINIO_ENDPOINT",
        "AUTODEV_MINIO_ACCESS_KEY",
        "AUTODEV_MINIO_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_settings_cache()


def test_local_profile_defaults_to_sqlite_and_stub_provider() -> None:
    """The local profile defaults to SQLite, the stub LLM, and local storage."""
    settings = Settings()

    assert settings.autodev_profile == "local"
    assert settings.database_url.startswith("sqlite:///")
    assert settings.llm_provider == "stub"
    assert settings.storage_backend == "local"


def test_prod_profile_requires_postgres_redis_and_minio() -> None:
    """The prod profile rejects defaults, reporting every missing requirement."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(autodev_profile="prod")

    message = str(excinfo.value)
    assert "prod profile requires DATABASE_URL to use PostgreSQL" in message
    assert "prod profile requires AUTODEV_JOB_BACKEND=redis" in message
    assert "prod profile requires AUTODEV_EVENT_BUS=redis" in message
    assert "prod profile requires AUTODEV_REDIS_URL" in message
    assert "prod profile requires STORAGE_BACKEND=s3" in message
    assert "prod profile requires MinIO/S3 settings" in message


def test_prod_profile_accepts_explicit_postgres_redis_and_s3() -> None:
    """The prod profile accepts a fully configured Postgres/Redis/S3 setup."""
    settings = Settings(
        autodev_profile="prod",
        database_url="postgresql://autodev:svc-db-secret@postgres:5432/autodev",
        autodev_job_backend="redis",
        autodev_event_bus="redis",
        autodev_redis_url="redis://redis:6379/0",
        storage_backend="s3",
        autodev_minio_endpoint="minio:9000",
        autodev_minio_access_key="svc-access-key",
        autodev_minio_secret_key="svc-secret-key",
    )

    assert settings.autodev_job_backend == "redis"
    assert settings.autodev_event_bus == "redis"
    assert settings.storage_backend == "s3"


def test_prod_profile_rejects_invalid_redis_url() -> None:
    """The prod profile rejects a Redis URL with an unsupported scheme."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            autodev_profile="prod",
            database_url="postgresql://autodev:svc-db-secret@postgres:5432/autodev",
            autodev_job_backend="redis",
            autodev_event_bus="redis",
            autodev_redis_url="http://redis:6379/0",
            storage_backend="s3",
            autodev_minio_endpoint="minio:9000",
            autodev_minio_access_key="svc-access-key",
            autodev_minio_secret_key="svc-secret-key",
        )

    assert "AUTODEV_REDIS_URL must start with redis:// or rediss://" in str(excinfo.value)


def test_settings_file_loads_below_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings-file values fill gaps left by env vars, which still take priority."""
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
    """The redacted settings dump masks every configured secret field."""
    settings = Settings(
        openai_api_key="sk-test",
        autodev_api_token="token-test",
        autodev_minio_secret_key="minio-secret",
    )

    redacted = settings.redacted_model_dump()

    assert redacted["openai_api_key"] == "***"
    assert redacted["autodev_api_token"] == "***"
    assert redacted["autodev_minio_secret_key"] == "***"


def test_trusted_in_process_plugin_ids_are_normalized() -> None:
    """The trust allowlist is parsed, stripped, and deduplicated."""
    settings = Settings(
        autodev_trusted_in_process_plugins="acme/one, acme/two,acme/one"
    )

    assert settings.trusted_in_process_plugin_ids() == frozenset(
        {"acme/one", "acme/two"}
    )


def test_redacted_dump_masks_credential_bearing_urls() -> None:
    """Passwords embedded in DATABASE_URL/AUTODEV_REDIS_URL never reach a dump."""
    settings = Settings(
        autodev_profile="prod",
        database_url="postgresql://svc:db-secret@postgres:5432/autodev",
        autodev_job_backend="redis",
        autodev_event_bus="redis",
        autodev_redis_url="redis://:redis-secret@redis:6379/0",
        storage_backend="s3",
        autodev_minio_endpoint="minio:9000",
        autodev_minio_access_key="service-access-key",
        autodev_minio_secret_key="service-secret-key",
    )

    redacted = settings.redacted_model_dump()

    assert redacted["database_url"] == "***"
    assert redacted["autodev_redis_url"] == "***"
    assert redacted["autodev_minio_access_key"] == "***"
    assert redacted["autodev_minio_secret_key"] == "***"
    assert "db-secret" not in repr(redacted)
    assert "redis-secret" not in repr(redacted)


def test_redacted_dump_keeps_credential_free_urls_usable() -> None:
    """A SQLite/local-mode URL with no embedded password is not masked."""
    settings = Settings(database_url="sqlite:///./autodev.db", autodev_redis_url="")

    redacted = settings.redacted_model_dump()

    assert redacted["database_url"] == "sqlite:///./autodev.db"
    assert redacted["autodev_redis_url"] == ""


def test_prod_profile_requires_a_postgres_password() -> None:
    """An empty PostgreSQL password is rejected in production."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            autodev_profile="prod",
            database_url="postgresql://svc@postgres:5432/autodev",
            autodev_job_backend="redis",
            autodev_event_bus="redis",
            autodev_redis_url="redis://redis:6379/0",
            storage_backend="s3",
            autodev_minio_endpoint="minio:9000",
            autodev_minio_access_key="svc-access-key",
            autodev_minio_secret_key="svc-secret-key",
        )

    assert "prod profile requires a PostgreSQL password" in str(excinfo.value)


@pytest.mark.parametrize(
    "password", ["autodev", "minioadmin", "password", "changeme", "change-me", "PASSWORD"]
)
def test_prod_profile_rejects_known_default_postgres_password(password: str) -> None:
    """Every known insecure default PostgreSQL password is rejected, case-insensitively."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            autodev_profile="prod",
            database_url=f"postgresql://svc:{password}@postgres:5432/autodev",
            autodev_job_backend="redis",
            autodev_event_bus="redis",
            autodev_redis_url="redis://redis:6379/0",
            storage_backend="s3",
            autodev_minio_endpoint="minio:9000",
            autodev_minio_access_key="svc-access-key",
            autodev_minio_secret_key="svc-secret-key",
        )

    assert "prod profile rejects known default PostgreSQL credentials" in str(excinfo.value)


@pytest.mark.parametrize("default_value", ["autodev", "minioadmin", "password", "changeme", "change-me"])
def test_prod_profile_rejects_known_default_minio_credentials(default_value: str) -> None:
    """Known default MinIO access/secret keys are rejected in production."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            autodev_profile="prod",
            database_url="postgresql://svc:svc-db-secret@postgres:5432/autodev",
            autodev_job_backend="redis",
            autodev_event_bus="redis",
            autodev_redis_url="redis://redis:6379/0",
            storage_backend="s3",
            autodev_minio_endpoint="minio:9000",
            autodev_minio_access_key=default_value,
            autodev_minio_secret_key="svc-secret-key",
        )

    assert "prod profile rejects known default AUTODEV_MINIO_ACCESS_KEY" in str(excinfo.value)
