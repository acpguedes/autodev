"""Runtime configuration storage and helpers.

E61-S2 composes the active configuration from three layers, each a sparse
JSON document, deep-merged per field in this order (lowest to highest
priority): internal defaults (:meth:`RuntimeConfigService._env_default_document`,
itself seeded from environment variables for backward compatibility) ->
the global layer (:func:`backend.config.paths.global_config_path`, shared by
every project) -> the project layer (:attr:`RuntimeConfigService.config_path`,
``AUTODEV_CONFIG_PATH`` or ``<project root>/autodev.config.json``). A key
missing from a layer's document is simply not applied -- the layer below
still provides it. This is what makes an explicit ``False``/``0``/``""``
survive composition: presence of the key is the only signal, never whether
its value is falsy (see :func:`_deep_merge`).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.config.paths import CONFIG_FILE_NAME
from backend.config.paths import global_config_path as _default_global_config_path
from backend.llm.factory import DEFAULT_OLLAMA_BASE_URL


DEFAULT_CONFIG_FILE_NAME = CONFIG_FILE_NAME

# Placeholder returned to clients instead of the stored LLM API key. When a
# client PUTs this value back unchanged, the previously stored key is preserved
# rather than being overwritten with the placeholder.
API_KEY_REDACTION = "***"

#: Sentinel distinguishing "key absent from the lower layer" from "key
#: present with a ``None``/falsy value" in :func:`_diff_document`.
_MISSING = object()


class ConfigFileError(ValueError):
    """Raised when a configuration layer's file exists but cannot be used.

    Carries both the offending file path and the underlying problem so a
    broken file is never silently treated the same as an absent one --
    :meth:`RuntimeConfigService._read_layer_raw` only returns ``{}`` for a
    *missing* file; an existing-but-invalid one always raises this instead.
    """

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Invalid configuration file at {path}: {reason}")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* onto *base*, field by field.

    A key present in *override* replaces the corresponding *base* value,
    unless both values are themselves dicts, in which case they are merged
    recursively rather than one wholesale replacing the other. A key absent
    from *override* is left untouched -- this is the mechanism behind
    "absence is key-absence, never falsiness": an explicit ``False``/``0``/
    ``""`` in *override* always wins because it is a present key, not a
    falsy value being compared away.

    Args:
        base: The lower-priority document.
        override: The higher-priority document.

    Returns:
        A new, merged dict. Neither input is mutated.
    """
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _diff_document(inherited: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of *incoming* that differs from *inherited*, recursively.

    Used by :meth:`RuntimeConfigService.save` so a value that already comes
    from a lower layer (defaults or global config) is never duplicated into
    the project file merely because the full materialized config carries it
    -- the mechanism behind E61-S2-T4's "no credential is copied from the
    global layer into a project file by inheritance". A nested dict is kept
    only if at least one of its leaves actually differs; an unchanged leaf
    is dropped so the project file never re-states a value a lower layer
    already provides.

    Args:
        inherited: What the config would be without the project layer (i.e.
            defaults deep-merged with the global layer).
        incoming: The full, materialized document about to be saved.

    Returns:
        The sparse document to persist as the project layer.
    """
    delta: dict[str, Any] = {}
    for key, value in incoming.items():
        base_value = inherited.get(key, _MISSING)
        if isinstance(value, dict) and isinstance(base_value, dict):
            nested = _diff_document(base_value, value)
            if nested:
                delta[key] = nested
        elif value != base_value:
            delta[key] = value
    return delta


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

    def __init__(
        self,
        config_path: Path | None = None,
        default_project_root: Path | None = None,
        global_config_path: Path | None = None,
    ) -> None:
        self._default_project_root = (default_project_root or self._env_or_cwd_project_root()).resolve()
        self._config_path = (config_path or self._resolve_config_path()).resolve()
        self._global_config_path = global_config_path or _default_global_config_path()

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def global_config_path(self) -> Path:
        return self._global_config_path

    def load(self) -> RuntimeConfig:
        """Load the composed configuration: defaults -> global layer -> project layer.

        Each layer is a sparse document (E61-S2-T1): a key a layer does not
        set is simply never applied, so the layer below still provides it --
        this is what lets a project override one field while inheriting
        every other one from the global layer.

        Returns:
            The fully composed, normalized configuration.

        Raises:
            ConfigFileError: If the global or the project configuration file
                exists but is not valid JSON, is not a JSON object, or does
                not validate against :class:`RuntimeConfig` once composed
                (E61-S2-T3) -- an invalid file is never treated as absent.
        """
        document = self._env_default_document()
        document = _deep_merge(document, self._read_layer_raw(self._global_config_path))
        document = _deep_merge(document, self._read_layer_raw(self._config_path))
        try:
            config = RuntimeConfig.model_validate(document)
        except ValidationError as exc:
            raise ConfigFileError(self._config_path, str(exc)) from exc
        return self._normalize(config)

    def save(self, config: RuntimeConfig) -> RuntimeConfig:
        """Persist *config*, writing only the fields the project layer actually overrides.

        A field whose value already equals what the defaults+global layers
        would produce on their own is left out of the project file entirely
        (E61-S2-T4): the project layer must never duplicate an inherited
        value -- a credential in particular -- merely because the full
        materialized ``RuntimeConfig`` passed in happens to carry it.

        Args:
            config: The full, materialized configuration to persist.

        Returns:
            The normalized configuration, as it will read back from
            :meth:`load` (same merged view; the project file itself may hold
            a strict subset of these fields).
        """
        normalized = self._normalize(config)
        inherited_document = _deep_merge(
            self._env_default_document(), self._read_layer_raw(self._global_config_path)
        )
        project_document = _diff_document(inherited_document, normalized.model_dump())

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(project_document, indent=2) + "\n")
        # The persisted config may hold the plaintext LLM API key — restrict
        # it to the owner so other local users cannot read the secret.
        try:
            os.chmod(self._config_path, 0o600)
        except OSError:  # pragma: no cover - platform-dependent (e.g. Windows)
            pass
        return normalized

    def update(self, payload: RuntimeConfig | dict[str, Any]) -> RuntimeConfig:
        config = payload if isinstance(payload, RuntimeConfig) else RuntimeConfig.model_validate(payload)
        # Preserve the stored secret when the client echoes back the redaction
        # placeholder instead of a real key.
        if config.llm.api_key.strip() == API_KEY_REDACTION:
            config = config.model_copy(deep=True)
            config.llm.api_key = self.load().llm.api_key
        return self.save(config)

    def load_document(self, *, redact_secrets: bool = False) -> RuntimeConfigDocument:
        config = self.load()
        instructions = self.build_instructions(config)
        if redact_secrets:
            config = self._redact(config)
        return RuntimeConfigDocument(config=config, instructions=instructions)

    def _redact(self, config: RuntimeConfig) -> RuntimeConfig:
        redacted = config.model_copy(deep=True)
        if redacted.llm.api_key:
            redacted.llm.api_key = API_KEY_REDACTION
        return redacted

    def build_instructions(self, config: RuntimeConfig | None = None) -> RuntimeInstructions:
        active_config = config or self.load()
        config_json = self._redact(active_config).model_dump_json(indent=2)
        api_key_display = API_KEY_REDACTION if active_config.llm.api_key else ""
        env_lines = [
            f"LLM_PROVIDER={active_config.llm.provider}",
            f"OPENAI_API_KEY={api_key_display}",
            f"OPENAI_MODEL={active_config.llm.model}",
            f"OPENAI_BASE_URL={active_config.llm.base_url}",
            f"OLLAMA_BASE_URL={self._resolve_ollama_base_url(active_config)}",
            f"OPENAI_TEMPERATURE={active_config.llm.temperature}",
            f"AUTODEV_PROJECT_ROOT={active_config.repository.project_root}",
        ]
        return RuntimeInstructions(
            config_path=str(self._config_path),
            config_file_example=config_json,
            env_file_example="\n".join(env_lines),
            notes=[
                "A UI grava a configuração em um arquivo JSON local para manter estado fora do prompt.",
                "autodev.config.json é a fonte de configuração do AutoDev (LLM e project root); .env não precisa duplicar esses valores — o exemplo abaixo é só para inspeção/depuração.",
                "O diretório configurado passa a ser usado pelo endpoint de contexto de repositório e pelo Navigator agent.",
                "LLM_PROVIDER=stub preserva um caminho totalmente local e determinístico quando não houver chave de API.",
                "LLM_PROVIDER=ollama habilita um caminho local first-class usando a API compatível com OpenAI do Ollama.",
            ],
        )

    def apply_to_environment(self, config: RuntimeConfig | None = None) -> RuntimeConfig:
        active_config = self._normalize(config or self.load())

        os.environ["LLM_PROVIDER"] = active_config.llm.provider
        os.environ["OPENAI_MODEL"] = active_config.llm.model
        os.environ["OPENAI_BASE_URL"] = active_config.llm.base_url
        os.environ["OLLAMA_BASE_URL"] = self._resolve_ollama_base_url(active_config)
        os.environ["OPENAI_TEMPERATURE"] = str(active_config.llm.temperature)
        os.environ["AUTODEV_PROJECT_ROOT"] = active_config.repository.project_root

        if active_config.llm.api_key:
            os.environ["OPENAI_API_KEY"] = active_config.llm.api_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)

        return active_config

    @staticmethod
    def _env_or_cwd_project_root() -> Path:
        """Resolve the default project root: ``AUTODEV_PROJECT_ROOT`` if set, else the launch cwd."""
        configured = os.getenv("AUTODEV_PROJECT_ROOT", "").strip()
        return Path(configured) if configured else Path.cwd()

    def _resolve_config_path(self) -> Path:
        """Resolve the ``autodev.config.json`` path.

        ``AUTODEV_CONFIG_PATH`` wins when set. Otherwise the file is looked
        up under the project the service is pointed at
        (``self._default_project_root``, itself derived from
        ``AUTODEV_PROJECT_ROOT``) rather than the directory the process
        happened to be launched from.
        """
        configured = os.getenv("AUTODEV_CONFIG_PATH", "").strip()
        if configured:
            return Path(configured)
        return self._default_project_root / DEFAULT_CONFIG_FILE_NAME

    def _env_default_document(self) -> dict[str, Any]:
        """Build the bottom configuration layer: field defaults seeded from the environment.

        This is the lowest-priority layer in the
        ``internal defaults -> global config -> project config`` composition
        (E61-S2-T1). It is :class:`RuntimeConfig`'s own field defaults, with
        a handful seeded from environment variables for backward
        compatibility with the pre-E61-S2 behavior (``LLM_PROVIDER``,
        ``OPENAI_*``, ``AUTODEV_PROJECT_ROOT``) -- unset env vars leave the
        plain pydantic default in place.

        Returns:
            A plain, JSON-shaped dict (not yet validated or normalized).
        """
        document = RuntimeConfig().model_dump()
        llm = document["llm"]
        llm["provider"] = os.getenv("LLM_PROVIDER", llm["provider"])
        llm["model"] = os.getenv("OPENAI_MODEL", llm["model"])
        llm["base_url"] = os.getenv("OPENAI_BASE_URL", llm["base_url"])
        llm["api_key"] = os.getenv("OPENAI_API_KEY", llm["api_key"])
        temperature = os.getenv("OPENAI_TEMPERATURE")
        if temperature is not None:
            llm["temperature"] = float(temperature)
        document["repository"]["project_root"] = (
            os.getenv("AUTODEV_PROJECT_ROOT", "").strip() or str(self._default_project_root)
        )
        return document

    def _read_layer_raw(self, path: Path) -> dict[str, Any]:
        """Read one configuration layer's raw JSON document.

        Args:
            path: The layer's file path.

        Returns:
            The parsed document, or ``{}`` if the file does not exist --
            a missing layer simply contributes nothing.

        Raises:
            ConfigFileError: If the file exists but is not valid JSON or is
                not a JSON object (E61-S2-T3): an existing-but-broken file
                is never treated the same as an absent one.
        """
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ConfigFileError(path, f"invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ConfigFileError(path, "must contain a JSON object")
        return payload

    def _normalize(self, config: RuntimeConfig) -> RuntimeConfig:
        """Apply structural normalization that is not itself a default-collapse.

        Unlike the pre-E61-S2 implementation, this never replaces an
        explicitly set falsy value (``""``, and by the same shape a future
        ``False``/``0``) with a default -- that is now the composition's
        job (:meth:`load`): a field missing from every layer already
        resolves to the internal default via :meth:`_env_default_document`,
        so by the time a config reaches this method every field has already
        received its correctly layered value. ``project_root`` is the one
        exception: an empty path carries no distinct meaning of its own (see
        :meth:`_resolve_project_root`), so it still falls back rather than
        resolving to a nonsensical empty path.
        """
        normalized = config.model_copy(deep=True)
        normalized.llm.provider = normalized.llm.provider.strip().lower()
        normalized.llm.model = normalized.llm.model.strip()
        normalized.llm.base_url = normalized.llm.base_url.strip()
        normalized.llm.api_key = normalized.llm.api_key.strip()
        normalized.repository.project_root = self._resolve_project_root(normalized.repository.project_root)
        normalized.repository.repository_label = normalized.repository.repository_label.strip()
        normalized.repository.default_goal = normalized.repository.default_goal.strip()
        return normalized

    def _resolve_ollama_base_url(self, config: RuntimeConfig) -> str:
        configured_base_url = config.llm.base_url.strip()
        if config.llm.provider == "ollama":
            return configured_base_url or DEFAULT_OLLAMA_BASE_URL
        return configured_base_url

    def _resolve_project_root(self, value: str) -> str:
        candidate = Path(value).expanduser() if value.strip() else self._default_project_root
        return str(candidate.resolve())


@lru_cache(maxsize=1)
def get_runtime_config_service() -> RuntimeConfigService:
    return RuntimeConfigService()


def reset_runtime_config_cache() -> None:
    """Clear the cached runtime config service — for use in tests.

    The service resolves its config path from ``AUTODEV_CONFIG_PATH`` at
    construction time, so tests that point that variable at an isolated path
    must clear this cache to avoid leaking the repository's persisted
    ``autodev.config.json`` into the test environment.
    """
    get_runtime_config_service.cache_clear()


__all__ = [
    "API_KEY_REDACTION",
    "ConfigFileError",
    "LLMSettings",
    "RepositorySettings",
    "RuntimeConfig",
    "RuntimeConfigDocument",
    "RuntimeConfigService",
    "RuntimeInstructions",
    "get_runtime_config_service",
    "reset_runtime_config_cache",
]
