"""Contract tests for the ``/v2/provider-config`` API (E16-S4-T4).

Mirrors the ``client`` fixture in ``backend/tests/test_v2_api_contract.py``:
an isolated temp SQLite store, the deterministic stub LLM provider, and an
isolated ``autodev.config.json`` path so these tests never read or mutate the
repository's real persisted configuration.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config.runtime import API_KEY_REDACTION, reset_runtime_config_cache
from backend.config.settings import reset_settings_cache
from backend.llm.factory import get_chat_model
from backend.persistence.database import reset_store_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A TestClient on an isolated temp SQLite store and isolated provider config file."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'provider-config-v2.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("AUTODEV_CONFIG_PATH", str(tmp_path / "isolated.config.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_runtime_config_cache()
    reset_settings_cache()
    reset_store_cache()
    get_chat_model.cache_clear()
    from backend.api.main import app

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_store_cache()
    reset_runtime_config_cache()
    get_chat_model.cache_clear()


class TestProviderConfigV2:
    """``GET``/``PUT /v2/provider-config`` read and persist LLM provider settings."""

    def test_get_provider_config_happy_path(self, client: TestClient) -> None:
        response = client.get("/v2/provider-config")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["llm"]["provider"] == "stub"

    def test_update_provider_config_round_trip(self, client: TestClient) -> None:
        current = client.get("/v2/provider-config").json()
        updated_llm = {
            **current["llm"],
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-test-secret",
        }
        response = client.put("/v2/provider-config", json={"llm": updated_llm})
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["llm"]["provider"] == "openai"
        assert body["llm"]["model"] == "gpt-4o"
        # The API key is never echoed back in plaintext.
        assert body["llm"]["api_key"] == API_KEY_REDACTION

    def test_update_provider_config_preserves_secret_on_redacted_echo(self, client: TestClient) -> None:
        client.put(
            "/v2/provider-config",
            json={"llm": {"provider": "openai", "model": "gpt-4o", "base_url": "", "temperature": 0.2, "api_key": "sk-original"}},
        ).raise_for_status()

        response = client.put(
            "/v2/provider-config",
            json={
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "base_url": "",
                    "temperature": 0.5,
                    "api_key": API_KEY_REDACTION,
                }
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["llm"]["model"] == "gpt-4o-mini"
        assert body["llm"]["temperature"] == 0.5
        assert body["llm"]["api_key"] == API_KEY_REDACTION

        # The real secret survived the redacted round trip: apply_to_environment
        # would have propagated it, and reloading confirms it is not blank.
        from backend.config.runtime import get_runtime_config_service

        raw_config = get_runtime_config_service().load()
        assert raw_config.llm.api_key == "sk-original"

    def test_update_provider_config_validation_error_shape(self, client: TestClient) -> None:
        response = client.put("/v2/provider-config", json={"llm": {"temperature": "not-a-number"}})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


class TestProviderStatusV2:
    """``GET /v2/provider-config/status`` derives a live status from stored settings."""

    def test_stub_provider_is_always_configured_and_healthy(self, client: TestClient) -> None:
        response = client.get("/v2/provider-config/status")
        assert response.status_code == 200
        body = response.json()
        assert body["schemaVersion"] == "2.0"
        assert body["name"] == "stub"
        assert body["configured"] is True
        assert body["healthy"] is True

    def test_remote_provider_without_api_key_is_not_configured(self, client: TestClient) -> None:
        # Persist directly through the runtime config service rather than via
        # ``PUT /v2/provider-config``: the latter calls ``apply_to_environment``,
        # which would set ``LLM_PROVIDER=openai`` with no ``OPENAI_API_KEY`` in
        # this process's environment — a combination the app's own ``Settings``
        # model deliberately rejects at construction time (see
        # ``backend/config/settings.py``), unrelated to this endpoint's status
        # derivation logic under test here.
        from backend.config.runtime import RuntimeConfig, get_runtime_config_service

        config_service = get_runtime_config_service()
        current = config_service.load()
        unconfigured = current.model_copy(
            update={"llm": current.llm.model_copy(update={"provider": "openai", "model": "gpt-4o", "api_key": ""})}
        )
        config_service.save(RuntimeConfig.model_validate(unconfigured.model_dump()))

        response = client.get("/v2/provider-config/status")
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "openai"
        assert body["configured"] is False
        assert body["healthy"] is False

    def test_remote_provider_with_api_key_is_configured(self, client: TestClient) -> None:
        client.put(
            "/v2/provider-config",
            json={"llm": {"provider": "openai", "model": "gpt-4o", "base_url": "", "temperature": 0.2, "api_key": "sk-present"}},
        ).raise_for_status()

        response = client.get("/v2/provider-config/status")
        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is True
        assert body["healthy"] is True
