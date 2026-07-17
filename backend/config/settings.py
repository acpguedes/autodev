"""Centralized application settings via pydantic-settings.

Single source of truth for all env-var driven configuration.  Import
``get_settings()`` to access a cached singleton; call
``reset_settings_cache()`` in test fixtures to get a fresh instance.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SECRET_FIELDS = {
    "openai_api_key",
    "autodev_api_token",
    "autodev_minio_secret_key",
}

# Shared defaults so the UI URL and the CORS allowlist can never drift: the
# default UI URL is, by definition, the first default CORS origin.
_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
_DEFAULT_UI_URL = _DEFAULT_CORS_ORIGINS.split(",")[0]


class Settings(BaseSettings):
    """Application settings sourced from environment variables and an optional JSON file."""

    model_config = SettingsConfigDict(env_ignore_empty=False, extra="ignore")

    # --- profile / settings source ---
    autodev_profile: Literal["local", "prod"] = "local"
    autodev_settings_file: str = ""

    # --- persistence ---
    database_url: str = "sqlite:///./autodev.db"

    # --- LLM ---
    llm_provider: str = "stub"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = ""
    openai_temperature: float = 0.2
    openai_verify_ssl: bool = True
    ollama_base_url: str = ""

    # --- workspace ---
    autodev_project_root: str = ""
    autodev_config_path: str = ""
    autodev_cors_origins: str = _DEFAULT_CORS_ORIGINS
    autodev_ui_url: str = _DEFAULT_UI_URL
    autodev_api_token: str = ""
    autodev_enable_hsts: bool = False
    autodev_host: str = "127.0.0.1"
    autodev_port: int = 8000

    # --- feature flags ---
    feature_repository_intelligence: bool = True
    feature_execution_plans: bool = True
    feature_patch_workflow: bool = True

    # --- execution / orchestration flags ---
    autodev_enable_patch_apply: bool = False
    autodev_enable_sandbox: bool = False
    autodev_sandbox_allow_local: bool = False
    autodev_sandbox_docker_network: str = "none"
    autodev_dynamic_orch: bool = False
    autodev_repo_provider: str = "lexical"

    # --- Redis / jobs / locks ---
    autodev_job_backend: Literal["inprocess", "redis"] = "inprocess"
    autodev_redis_url: str = ""

    # --- event bus (E9-S2-T2) ---
    autodev_event_bus: Literal["inmemory", "redis"] = "inmemory"

    # --- event store (E8-S2) ---
    autodev_event_store_enabled: bool = True
    autodev_event_retention_days: int = Field(default=30, ge=-1)

    # --- artifacts ---
    storage_backend: Literal["local", "s3"] = "local"
    autodev_artifact_dir: str = "/data/artifacts"
    autodev_minio_endpoint: str = ""
    autodev_minio_bucket: str = "autodev-artifacts"
    autodev_minio_access_key: str = ""
    autodev_minio_secret_key: str = ""
    autodev_minio_secure: bool = False

    # --- MCP (Model Context Protocol) ---
    autodev_mcp_exposed_skills: str = ""

    # --- observability ---
    otel_service_name: str = "autodev-backend"
    otel_exporter_otlp_endpoint: str = ""
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0.0, le=1.0)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Order settings sources so an ``AUTODEV_SETTINGS_FILE`` JSON file fills gaps left by env vars.

        Args:
            settings_cls: The settings class being configured.
            init_settings: Source providing values passed to ``__init__``.
            env_settings: Source providing values from environment variables.
            dotenv_settings: Source providing values from a ``.env`` file.
            file_secret_settings: Source providing values from Docker/K8s secret files.

        Returns:
            The ordered tuple of settings sources, highest priority first.
        """
        return (
            init_settings,
            env_settings,
            cls._json_settings_source,
            dotenv_settings,
            file_secret_settings,
        )

    @staticmethod
    def _json_settings_source() -> dict[str, Any]:
        """Load settings overrides from the file named by ``AUTODEV_SETTINGS_FILE``.

        Returns:
            The parsed settings mapping, or an empty dict if unset.

        Raises:
            ValueError: If the file does not exist or is not a JSON object
                (optionally nested under a ``"settings"`` key).
        """
        raw_path = os.getenv("AUTODEV_SETTINGS_FILE", "").strip()
        if not raw_path:
            return {}

        path = Path(raw_path).expanduser()
        if not path.exists():
            raise ValueError(f"AUTODEV_SETTINGS_FILE does not exist: {path}")

        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("AUTODEV_SETTINGS_FILE must contain a JSON object.")
        nested = payload.get("settings", payload)
        if not isinstance(nested, dict):
            raise ValueError("AUTODEV_SETTINGS_FILE 'settings' value must be an object.")
        return nested

    @model_validator(mode="after")
    def validate_profile(self) -> "Settings":
        """Validate cross-field constraints implied by ``autodev_profile``.

        Returns:
            This settings instance, unchanged aside from normalizing ``llm_provider``.

        Raises:
            ValueError: If the LLM provider or any profile-specific requirement is invalid.
        """
        errors: list[str] = []
        provider = self.llm_provider.strip().lower()
        if provider not in {"stub", "openai", "ollama"}:
            errors.append("LLM_PROVIDER must be one of: stub, openai, ollama")
        else:
            self.llm_provider = provider

        if provider == "openai" and not self.openai_api_key.strip():
            errors.append("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        if self.autodev_profile == "local":
            if not self.database_url.startswith("sqlite://"):
                errors.append("local profile requires DATABASE_URL to use SQLite")
        else:
            if not (
                self.database_url.startswith("postgresql://")
                or self.database_url.startswith("postgres://")
            ):
                errors.append("prod profile requires DATABASE_URL to use PostgreSQL")
            if self.autodev_job_backend != "redis":
                errors.append("prod profile requires AUTODEV_JOB_BACKEND=redis")
            if self.autodev_event_bus != "redis":
                errors.append("prod profile requires AUTODEV_EVENT_BUS=redis")
            if not self.autodev_redis_url.strip():
                errors.append("prod profile requires AUTODEV_REDIS_URL")
            elif urlparse(self.autodev_redis_url).scheme not in {"redis", "rediss"}:
                errors.append("AUTODEV_REDIS_URL must start with redis:// or rediss://")
            if self.storage_backend != "s3":
                errors.append("prod profile requires STORAGE_BACKEND=s3")
            if not (
                self.autodev_minio_endpoint.strip()
                and self.autodev_minio_access_key.strip()
                and self.autodev_minio_secret_key.strip()
            ):
                errors.append("prod profile requires MinIO/S3 settings")

        if errors:
            raise ValueError("; ".join(errors))
        return self

    def cors_origins(self) -> list[str]:
        """Parse the comma-separated ``autodev_cors_origins`` field into a list.

        Returns:
            The configured CORS origins, with blanks removed.
        """
        return [
            origin.strip()
            for origin in self.autodev_cors_origins.split(",")
            if origin.strip()
        ]

    def mcp_exposed_skills(self) -> list[str]:
        """Parse the comma-separated ``autodev_mcp_exposed_skills`` field into a list.

        Empty by default, so no skill is exposed through the MCP server
        (:class:`backend.mcp.server.McpServer`) until explicitly allowlisted
        (E9-S4-T3 least-privilege mapping).

        Returns:
            The configured MCP-exposed skill ids, with blanks removed.
        """
        return [
            skill_id.strip()
            for skill_id in self.autodev_mcp_exposed_skills.split(",")
            if skill_id.strip()
        ]

    def redacted_model_dump(self) -> dict[str, Any]:
        """Dump settings to a dict with secret fields masked.

        Returns:
            The settings as a dict, with values in :data:`_SECRET_FIELDS` replaced by ``"***"``.
        """
        data = self.model_dump()
        for key in _SECRET_FIELDS:
            if data.get(key):
                data[key] = "***"
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build and cache the process-wide :class:`Settings` singleton.

    Returns:
        The cached settings instance.
    """
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings instance — for use in tests."""
    get_settings.cache_clear()


__all__ = ["Settings", "get_settings", "reset_settings_cache"]
