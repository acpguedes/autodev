"""Runtime configuration storage and helpers."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


DEFAULT_CONFIG_FILE_NAME = "autodev.config.json"


class LLMSettings(BaseModel):
    """Persisted LLM provider settings."""

    provider: str = Field(default="stub")
    model: str = Field(default="gpt-4o-mini")
    base_url: str = Field(default="")
    temperature: float = Field(default=0.2)
    api_key: str = Field(default="")


class RepositorySettings(BaseModel):
    """Persisted repository/workspace settings."""

    project_root: str = Field(default_factory=lambda: str(Path.cwd()))
    repository_label: str = Field(default="Current workspace")
    default_goal: str = Field(default="Bootstrap AutoDev project")


class RuntimeConfig(BaseModel):
    """Top-level persisted application configuration."""

    version: int = 1
    llm: LLMSettings = Field(default_factory=LLMSettings)
    repository: RepositorySettings = Field(default_factory=RepositorySettings)


class RuntimeInstructions(BaseModel):
    """Instructional metadata returned to UI/API clients."""

    config_path: str
    config_file_example: str
    env_file_example: str
    notes: list[str]


class RuntimeConfigDocument(BaseModel):
    """Combined config document returned by the API."""

    config: RuntimeConfig
    instructions: RuntimeInstructions


class RuntimeConfigService:
    """Load, persist, and apply runtime configuration."""

    def __init__(self, config_path: Path | None = None, default_project_root: Path | None = None) -> None:
        self._default_project_root = (default_project_root or Path.cwd()).resolve()
        self._config_path = (config_path or self._resolve_config_path()).resolve()

    @property
    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> RuntimeConfig:
        if not self._config_path.exists():
            return self._default_config()

        payload = json.loads(self._config_path.read_text())
        return RuntimeConfig.model_validate(payload)

    def save(self, config: RuntimeConfig) -> RuntimeConfig:
        normalized = self._normalize(config)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(normalized.model_dump_json(indent=2) + "\n")
        return normalized

    def update(self, payload: RuntimeConfig | dict[str, Any]) -> RuntimeConfig:
        config = payload if isinstance(payload, RuntimeConfig) else RuntimeConfig.model_validate(payload)
        return self.save(config)

    def load_document(self) -> RuntimeConfigDocument:
        config = self.load()
        return RuntimeConfigDocument(config=config, instructions=self.build_instructions(config))

    def build_instructions(self, config: RuntimeConfig | None = None) -> RuntimeInstructions:
        active_config = config or self.load()
        config_json = active_config.model_dump_json(indent=2)
        env_lines = [
            f"LLM_PROVIDER={active_config.llm.provider}",
            f"OPENAI_API_KEY={active_config.llm.api_key}",
            f"OPENAI_MODEL={active_config.llm.model}",
            f"OPENAI_BASE_URL={active_config.llm.base_url}",
            f"OPENAI_TEMPERATURE={active_config.llm.temperature}",
            f"AUTODEV_PROJECT_ROOT={active_config.repository.project_root}",
        ]
        return RuntimeInstructions(
            config_path=str(self._config_path),
            config_file_example=config_json,
            env_file_example="\n".join(env_lines),
            notes=[
                "A UI grava a configuração em um arquivo JSON local para manter estado fora do prompt.",
                "Se preferir, copie os exemplos para .env antes de iniciar os serviços.",
                "O diretório configurado passa a ser usado pelo endpoint de contexto de repositório e pelo Navigator agent.",
                "LLM_PROVIDER=stub preserva um caminho totalmente local e determinístico quando não houver chave de API.",
            ],
        )

    def apply_to_environment(self, config: RuntimeConfig | None = None) -> RuntimeConfig:
        active_config = self._normalize(config or self.load())

        os.environ["LLM_PROVIDER"] = active_config.llm.provider
        os.environ["OPENAI_MODEL"] = active_config.llm.model
        os.environ["OPENAI_BASE_URL"] = active_config.llm.base_url
        os.environ["OPENAI_TEMPERATURE"] = str(active_config.llm.temperature)
        os.environ["AUTODEV_PROJECT_ROOT"] = active_config.repository.project_root

        if active_config.llm.api_key:
            os.environ["OPENAI_API_KEY"] = active_config.llm.api_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)

        return active_config

    def _resolve_config_path(self) -> Path:
        configured = os.getenv("AUTODEV_CONFIG_PATH", "").strip()
        if configured:
            return Path(configured)
        return Path.cwd() / DEFAULT_CONFIG_FILE_NAME

    def _default_config(self) -> RuntimeConfig:
        return self._normalize(
            RuntimeConfig(
                repository=RepositorySettings(project_root=str(self._default_project_root))
            )
        )

    def _normalize(self, config: RuntimeConfig) -> RuntimeConfig:
        normalized = config.model_copy(deep=True)
        normalized.llm.provider = normalized.llm.provider.strip().lower() or "stub"
        normalized.llm.model = normalized.llm.model.strip() or "gpt-4o-mini"
        normalized.llm.base_url = normalized.llm.base_url.strip()
        normalized.llm.api_key = normalized.llm.api_key.strip()
        normalized.repository.project_root = self._resolve_project_root(normalized.repository.project_root)
        normalized.repository.repository_label = (
            normalized.repository.repository_label.strip() or "Current workspace"
        )
        normalized.repository.default_goal = (
            normalized.repository.default_goal.strip() or "Bootstrap AutoDev project"
        )
        return normalized

    def _resolve_project_root(self, value: str) -> str:
        candidate = Path(value).expanduser() if value.strip() else self._default_project_root
        return str(candidate.resolve())


@lru_cache(maxsize=1)
def get_runtime_config_service() -> RuntimeConfigService:
    return RuntimeConfigService()


__all__ = [
    "LLMSettings",
    "RepositorySettings",
    "RuntimeConfig",
    "RuntimeConfigDocument",
    "RuntimeConfigService",
    "RuntimeInstructions",
    "get_runtime_config_service",
]
