"""Tests for secret-value envelope encryption (E33-S1-T2, ADR-014)."""

from __future__ import annotations

import pytest

from backend.config.settings import Settings
from backend.secret_store.crypto import InvalidToken, decrypt_secret_value, encrypt_secret_value


def _settings(key: str = "test-only-key-material") -> Settings:
    return Settings(_env_file=None, autodev_secret_encryption_key=key)  # type: ignore[call-arg]


def test_encrypt_then_decrypt_roundtrips() -> None:
    settings = _settings()
    ciphertext = encrypt_secret_value("hunter2", settings=settings)
    assert ciphertext != "hunter2"
    assert decrypt_secret_value(ciphertext, settings=settings) == "hunter2"


def test_ciphertext_is_not_decryptable_under_a_different_key() -> None:
    ciphertext = encrypt_secret_value("hunter2", settings=_settings("key-a"))
    with pytest.raises(InvalidToken):
        decrypt_secret_value(ciphertext, settings=_settings("key-b"))


def test_local_mode_ephemeral_key_still_roundtrips_within_the_same_process() -> None:
    settings = _settings(key="")
    ciphertext = encrypt_secret_value("hunter2", settings=settings)
    assert decrypt_secret_value(ciphertext, settings=settings) == "hunter2"
