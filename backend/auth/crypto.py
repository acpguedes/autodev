"""Service-key hashing/parsing and refresh-token encryption.

Service-key secrets are hashed with SHA-256 and compared with
:func:`hmac.compare_digest`; the raw secret is never persisted, only its
hash. Browser refresh tokens are encrypted at rest with Fernet
(symmetric authenticated encryption), keyed by
``AUTODEV_SESSION_ENCRYPTION_KEY``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

SERVICE_KEY_PREFIX = "adk_live"


def generate_key_id() -> str:
    """Generate a new, non-secret service-key identifier.

    Returns:
        A URL-safe, 16-character hex identifier.
    """
    return secrets.token_hex(8)


def generate_service_key(key_id: str) -> tuple[str, str]:
    """Generate a new service-key secret and its stored hash.

    Args:
        key_id: The non-secret identifier this secret is minted for.

    Returns:
        A ``(presented_key, secret_hash)`` pair: ``presented_key`` is shown to
        the caller exactly once; ``secret_hash`` is what gets persisted.
    """
    secret = secrets.token_urlsafe(32)
    presented_key = f"{SERVICE_KEY_PREFIX}_{key_id}_{secret}"
    return presented_key, hash_secret(secret)


def parse_service_key(presented: str) -> tuple[str, str] | None:
    """Split a presented service key into its key id and raw secret.

    Args:
        presented: The full ``adk_live_<key-id>_<secret>`` credential.

    Returns:
        A ``(key_id, secret)`` pair, or ``None`` if ``presented`` is not
        shaped like a service key.
    """
    prefix = f"{SERVICE_KEY_PREFIX}_"
    if not presented.startswith(prefix):
        return None
    key_id, separator, secret = presented[len(prefix) :].partition("_")
    if not separator or not key_id or not secret:
        return None
    return key_id, secret


def hash_secret(secret: str) -> str:
    """Hash a secret for at-rest storage.

    Args:
        secret: The raw secret to hash.

    Returns:
        The hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_secret(secret: str, expected_hash: str) -> bool:
    """Constant-time comparison of a presented secret against its stored hash.

    Args:
        secret: The raw secret presented by the caller.
        expected_hash: The hash on file for this credential.

    Returns:
        ``True`` if the secret's hash matches, without leaking timing
        information about a partial match.
    """
    return hmac.compare_digest(hash_secret(secret), expected_hash)


def derive_fernet(key_material: str) -> Fernet:
    """Derive a valid Fernet cipher from arbitrary configured key material.

    ``AUTODEV_SESSION_ENCRYPTION_KEY`` is an operator-provided string of any
    length, but Fernet requires a 32-byte URL-safe base64 key; this hashes
    the configured material down to exactly that shape.

    Args:
        key_material: The configured (or ephemeral, for local mode) session
            encryption key.

    Returns:
        A :class:`~cryptography.fernet.Fernet` cipher.
    """
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_refresh_token(token: str, fernet: Fernet) -> str:
    """Encrypt a browser session's refresh token for at-rest storage.

    Args:
        token: The raw refresh token issued by the OIDC provider.
        fernet: Cipher derived from :func:`derive_fernet`.

    Returns:
        The encrypted, storable ciphertext.
    """
    return fernet.encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_refresh_token(ciphertext: str, fernet: Fernet) -> str:
    """Decrypt a stored refresh token.

    Args:
        ciphertext: Value previously returned by
            :func:`encrypt_refresh_token`.
        fernet: Cipher derived from :func:`derive_fernet`.

    Returns:
        The raw refresh token.

    Raises:
        cryptography.fernet.InvalidToken: If ``ciphertext`` is malformed or
            was encrypted under a different key.
    """
    return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")


__all__ = [
    "SERVICE_KEY_PREFIX",
    "InvalidToken",
    "decrypt_refresh_token",
    "derive_fernet",
    "encrypt_refresh_token",
    "generate_key_id",
    "generate_service_key",
    "hash_secret",
    "parse_service_key",
    "verify_secret",
]
