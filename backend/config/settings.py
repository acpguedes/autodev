"""Centralized application settings via pydantic-settings.

Single source of truth for all env-var driven configuration.  Import
``get_settings()`` to access a cached singleton; call
``reset_settings_cache()`` in test fixtures to get a fresh instance.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=False, extra="ignore")

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

    # --- feature flags ---
    feature_repository_intelligence: bool = True
    feature_execution_plans: bool = True
    feature_patch_workflow: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings instance — for use in tests."""
    get_settings.cache_clear()


__all__ = ["Settings", "get_settings", "reset_settings_cache"]
