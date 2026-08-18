"""Envelope encryption for at-rest secret values (E33-S1-T2, ADR-014).

Reuses the Fernet-based encryption already established for browser
refresh tokens (:mod:`backend.auth.crypto`) rather than introducing a
second crypto primitive: :func:`~backend.auth.crypto.derive_fernet` hashes
arbitrary operator-provided key material down to a valid Fernet key, and
Fernet itself is authenticated symmetric encryption (an envelope around
each value), keyed by ``AUTODEV_SECRET_ENCRYPTION_KEY``.
"""

from __future__ import annotations

import secrets as _secrets_module
import threading

from backend.auth.crypto import InvalidToken, derive_fernet
from backend.config.settings import Settings, get_settings

_ephemeral_secret_key: str | None = None
_ephemeral_secret_key_lock = threading.Lock()

__all__ = ["InvalidToken", "decrypt_secret_value", "encrypt_secret_value", "fernet_for_settings"]


def _local_ephemeral_secret_key() -> str:
    """Return one process-lifetime random secret-encryption key.

    Used only when ``AUTODEV_SECRET_ENCRYPTION_KEY`` is unset (local mode),
    mirroring ``backend.auth.service._local_ephemeral_session_key``. Secrets
    written under this ephemeral key are unreadable across a process
    restart -- acceptable for local/dev use, never for production.
    """
    global _ephemeral_secret_key
    if _ephemeral_secret_key is None:
        with _ephemeral_secret_key_lock:
            if _ephemeral_secret_key is None:
                _ephemeral_secret_key = _secrets_module.token_urlsafe(32)
    return _ephemeral_secret_key


def fernet_for_settings(settings: Settings | None = None):  # type: ignore[no-untyped-def]
    """Derive the Fernet cipher for the currently configured secret-encryption key.

    Args:
        settings: Application settings; defaults to the cached settings.

    Returns:
        A :class:`~cryptography.fernet.Fernet` cipher.
    """
    active = settings or get_settings()
    key_material = active.autodev_secret_encryption_key.strip() or _local_ephemeral_secret_key()
    return derive_fernet(key_material)


def encrypt_secret_value(value: str, *, settings: Settings | None = None) -> str:
    """Encrypt a secret's plaintext value for at-rest storage.

    Args:
        value: The raw secret value.
        settings: Application settings; defaults to the cached settings.

    Returns:
        The encrypted, storable ciphertext.
    """
    return fernet_for_settings(settings).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret_value(ciphertext: str, *, settings: Settings | None = None) -> str:
    """Decrypt a stored secret value.

    Args:
        ciphertext: Value previously returned by :func:`encrypt_secret_value`.
        settings: Application settings; defaults to the cached settings.

    Returns:
        The raw secret value.

    Raises:
        InvalidToken: If ``ciphertext`` is malformed or was encrypted under
            a different key.
    """
    return fernet_for_settings(settings).decrypt(ciphertext.encode("ascii")).decode("utf-8")
