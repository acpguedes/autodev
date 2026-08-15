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
    "autodev_minio_access_key",
    "autodev_minio_secret_key",
    "otel_exporter_otlp_endpoint",
    "otel_exporter_otlp_traces_endpoint",
    "otel_exporter_otlp_metrics_endpoint",
    "otel_exporter_otlp_logs_endpoint",
    "autodev_oidc_client_secret",
    "autodev_session_encryption_key",
}

_CREDENTIAL_URL_FIELDS = {
    "database_url",
    "autodev_redis_url",
}

_KNOWN_INSECURE_DEFAULT_CREDENTIALS = frozenset(
    {"autodev", "minioadmin", "password", "changeme", "change-me"}
)


def _contains_url_password(value: str) -> bool:
    """Return whether a URL contains embedded password material.

    Args:
        value: Candidate URL.

    Returns:
        ``True`` if the URL has a password component, or if it cannot be
        parsed at all (treated as unsafe to display verbatim).
    """
    try:
        return urlparse(value).password is not None
    except ValueError:
        return True

# Shared defaults so the UI URL and the CORS allowlist can never drift: the
# default UI URL is, by definition, the first default CORS origin.
_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
_DEFAULT_UI_URL = _DEFAULT_CORS_ORIGINS.split(",")[0]

OtelSamplerName = Literal[
    "always_on",
    "always_off",
    "traceidratio",
    "parentbased_always_on",
    "parentbased_always_off",
    "parentbased_traceidratio",
]


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
    # Global default model for the provider-neutral gateway (E2-S6). Empty means
    # no global default: agents must then select a model, or the run fails
    # explicitly rather than silently picking one.
    llm_model: str = ""
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
    autodev_sandbox_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    autodev_dynamic_orch: bool = False
    autodev_repo_provider: str = "lexical"

    # --- plugin security (E11-S4) ---
    autodev_trusted_in_process_plugins: str = ""

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
    autodev_artifact_retention_days: int = Field(default=7, ge=-1)
    autodev_minio_endpoint: str = ""
    autodev_minio_bucket: str = "autodev-artifacts"
    autodev_minio_access_key: str = ""
    autodev_minio_secret_key: str = ""
    autodev_minio_secure: bool = False

    # --- backups (E8-S4, E11-S4) ---
    autodev_backup_status_path: str = ".autodev/backup-status.json"

    # --- MCP (Model Context Protocol) ---
    autodev_mcp_exposed_skills: str = ""

    # --- observability ---
    otel_enabled: bool = True
    otel_service_name: str = "autodev-backend"
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_traces_endpoint: str = ""
    otel_exporter_otlp_metrics_endpoint: str = ""
    otel_exporter_otlp_logs_endpoint: str = ""
    otel_traces_sampler: OtelSamplerName = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_metric_export_interval_ms: int = Field(default=5_000, ge=1_000)
    autodev_observability_trace_retention: str = Field(
        default="168h", pattern=r"^[1-9]\d*(?:s|m|h|d|w)$"
    )
    autodev_observability_metric_retention: str = Field(
        default="15d", pattern=r"^[1-9]\d*(?:s|m|h|d|w)$"
    )
    autodev_observability_log_retention: str = Field(
        default="168h", pattern=r"^[1-9]\d*(?:s|m|h|d|w)$"
    )

    # --- Control Plane authentication / RBAC / audit (E11-S2) ---
    autodev_oidc_issuer: str = ""
    autodev_oidc_audience: str = ""
    autodev_oidc_jwks_url: str = ""
    autodev_oidc_authorization_url: str = ""
    autodev_oidc_token_url: str = ""
    autodev_oidc_client_id: str = ""
    autodev_oidc_client_secret: str = ""
    autodev_oidc_role_claim: str = "roles"
    autodev_oidc_tenant_claim: str = "tenant_id"
    autodev_oidc_scope_claim: str = "scope"
    autodev_oidc_algorithms: str = "RS256"
    autodev_oidc_jwks_ttl_seconds: int = Field(default=3_600, ge=60)
    autodev_session_encryption_key: str = ""
    autodev_session_ttl_seconds: int = Field(default=28_800, ge=60)

    # --- Tenant quotas and run budgets (E11-S3, ADR-019) ---
    #: Local-mode (no explicit tenant policy) finite defaults.
    autodev_quota_local_max_concurrent_runs: int = Field(default=4, ge=1)
    autodev_quota_local_max_storage_bytes: int = Field(
        default=1 * 1024 * 1024 * 1024, ge=1
    )
    autodev_quota_local_requests_per_second: int = Field(default=20, ge=1)
    autodev_quota_local_monthly_token_limit: int = Field(default=20_000_000, ge=1)
    autodev_quota_local_monthly_cost_microusd: int = Field(
        default=100_000_000, ge=1
    )
    #: Default per-run budget, applied everywhere unless narrowed further.
    autodev_quota_default_run_max_tokens: int = Field(default=2_000_000, ge=1)
    autodev_quota_default_run_max_cost_microusd: int = Field(
        default=10_000_000, ge=1
    )
    autodev_quota_default_run_max_wall_clock_ms: int = Field(
        default=3_600_000, ge=1
    )
    autodev_quota_default_run_max_steps: int = Field(default=1_000, ge=1)
    #: Concurrency-lease lifecycle.
    autodev_quota_run_lease_seconds: int = Field(default=90, ge=1)
    autodev_quota_run_heartbeat_seconds: int = Field(default=30, ge=1)
    #: Production requires an explicit, durably-stored policy per tenant;
    #: local mode falls back to the finite defaults above.
    autodev_quota_production_requires_policy: bool = True

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
            raise ValueError(
                "AUTODEV_SETTINGS_FILE 'settings' value must be an object."
            )
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
            else:
                database_password = urlparse(self.database_url).password or ""
                if not database_password:
                    errors.append("prod profile requires a PostgreSQL password")
                elif database_password.casefold() in _KNOWN_INSECURE_DEFAULT_CREDENTIALS:
                    errors.append(
                        "prod profile rejects known default PostgreSQL credentials"
                    )
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
            for field_name, value in (
                ("AUTODEV_MINIO_ACCESS_KEY", self.autodev_minio_access_key),
                ("AUTODEV_MINIO_SECRET_KEY", self.autodev_minio_secret_key),
            ):
                if value.casefold() in _KNOWN_INSECURE_DEFAULT_CREDENTIALS:
                    errors.append(f"prod profile rejects known default {field_name}")

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

    def trusted_in_process_plugin_ids(self) -> frozenset[str]:
        """Parse the operator trust allowlist for in-process plugins.

        Returns:
            Normalized, non-empty plugin identifiers.
        """
        return frozenset(
            plugin_id.strip()
            for plugin_id in self.autodev_trusted_in_process_plugins.split(",")
            if plugin_id.strip()
        )

    def redacted_model_dump(self) -> dict[str, Any]:
        """Dump settings with secret and credential-bearing values masked.

        Returns:
            The settings as a dict. Values in :data:`_SECRET_FIELDS` are
            always replaced by ``"***"``; values in
            :data:`_CREDENTIAL_URL_FIELDS` are replaced by ``"***"`` only
            when they embed a URL password, so credential-free SQLite/Redis
            URLs remain usable for display.
        """
        data = self.model_dump()
        for key in _SECRET_FIELDS:
            if data.get(key):
                data[key] = "***"
        for key in _CREDENTIAL_URL_FIELDS:
            value = data.get(key)
            if isinstance(value, str) and value and _contains_url_password(value):
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


__all__ = ["OtelSamplerName", "Settings", "get_settings", "reset_settings_cache"]
