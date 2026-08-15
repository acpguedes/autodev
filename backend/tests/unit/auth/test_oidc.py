"""Contracts for JWT validation and PKCE login (Task 2)."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.auth.contracts import InvalidCredentialError, Role
from backend.auth.oidc import (
    OidcSettings,
    OidcValidator,
    build_authorization_url,
    generate_pkce_challenge,
)

ISSUER = "https://idp.example.com"
AUDIENCE = "autodev"


def _keypair() -> tuple[object, object]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _settings(**overrides: object) -> OidcSettings:
    base: dict[str, object] = {
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "jwks_url": f"{ISSUER}/.well-known/jwks.json",
        "authorization_url": f"{ISSUER}/authorize",
        "token_url": f"{ISSUER}/token",
        "client_id": "autodev-backend",
        "client_secret": "",
        "role_claim": "roles",
        "tenant_claim": "tenant_id",
        "scope_claim": "scope",
        "algorithms": ("RS256",),
        "jwks_ttl_seconds": 3600,
    }
    base.update(overrides)
    return OidcSettings(**base)  # type: ignore[arg-type]


def _validator_with_key(monkeypatch: pytest.MonkeyPatch, public_key: object) -> OidcValidator:
    validator = OidcValidator(_settings())
    monkeypatch.setattr(
        validator._jwks_client,  # noqa: SLF001 - internal test wiring
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=public_key),
    )
    return validator


def _token(private_key: object, **claim_overrides: object) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "roles": ["maintainer"],
        "scope": "run:read run:write",
        "exp": now + timedelta(minutes=5),
        "iat": now,
    }
    payload.update(claim_overrides)
    return pyjwt.encode(payload, private_key, algorithm="RS256")


def test_valid_token_builds_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed, correctly signed token builds the expected principal."""
    private_key, public_key = _keypair()
    validator = _validator_with_key(monkeypatch, public_key)
    principal = validator.validate(_token(private_key))
    assert principal.subject == "user-1"
    assert principal.tenant_id == "tenant-a"
    assert principal.roles == (Role.MAINTAINER,)
    assert principal.scopes == frozenset({"run:read", "run:write"})


def test_author_role_claim_normalizes_to_maintainer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A legacy 'author' role claim is accepted and normalized on ingestion."""
    private_key, public_key = _keypair()
    validator = _validator_with_key(monkeypatch, public_key)
    principal = validator.validate(_token(private_key, roles=["author"]))
    assert principal.roles == (Role.MAINTAINER,)


def test_wrong_issuer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token signed by a different issuer is rejected."""
    private_key, public_key = _keypair()
    validator = _validator_with_key(monkeypatch, public_key)
    with pytest.raises(InvalidCredentialError):
        validator.validate(_token(private_key, iss="https://evil.example.com"))


def test_wrong_audience_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token issued for a different audience is rejected."""
    private_key, public_key = _keypair()
    validator = _validator_with_key(monkeypatch, public_key)
    with pytest.raises(InvalidCredentialError):
        validator.validate(_token(private_key, aud="other-service"))


def test_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An expired token is rejected."""
    private_key, public_key = _keypair()
    validator = _validator_with_key(monkeypatch, public_key)
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    with pytest.raises(InvalidCredentialError):
        validator.validate(_token(private_key, exp=expired))


def test_missing_tenant_claim_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token missing the configured tenant claim is rejected."""
    private_key, public_key = _keypair()
    validator = _validator_with_key(monkeypatch, public_key)
    token = _token(private_key)
    del token  # the encoded token cannot omit a claim after signing
    now = datetime.now(timezone.utc)
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "roles": ["maintainer"],
        "exp": now + timedelta(minutes=5),
    }
    missing_tenant_token = pyjwt.encode(payload, private_key, algorithm="RS256")
    with pytest.raises(InvalidCredentialError):
        validator.validate(missing_tenant_token)


def test_missing_role_claim_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token missing the configured role claim is rejected."""
    private_key, public_key = _keypair()
    validator = _validator_with_key(monkeypatch, public_key)
    now = datetime.now(timezone.utc)
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "exp": now + timedelta(minutes=5),
    }
    missing_role_token = pyjwt.encode(payload, private_key, algorithm="RS256")
    with pytest.raises(InvalidCredentialError):
        validator.validate(missing_role_token)


def test_missing_scope_claim_defaults_to_no_narrowing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token without a scope claim is valid; it simply asserts no narrowing."""
    private_key, public_key = _keypair()
    validator = _validator_with_key(monkeypatch, public_key)
    now = datetime.now(timezone.utc)
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "roles": ["viewer"],
        "exp": now + timedelta(minutes=5),
    }
    token = pyjwt.encode(payload, private_key, algorithm="RS256")
    principal = validator.validate(token)
    assert principal.scopes == frozenset()


def test_invalid_signature_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token signed by a key other than the one JWKS resolves is rejected."""
    signing_key, _unused_public_key = _keypair()
    _other_private_key, verification_public_key = _keypair()
    validator = _validator_with_key(monkeypatch, verification_public_key)
    with pytest.raises(InvalidCredentialError):
        validator.validate(_token(signing_key))


def test_unresolvable_signing_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JWKS lookup failure (e.g. an unknown ``kid``) is a credential error, not a crash."""
    private_key, _public_key = _keypair()
    validator = OidcValidator(_settings())

    def _raise(token: str) -> object:
        raise pyjwt.PyJWKClientError("unable to find a signing key")

    monkeypatch.setattr(validator._jwks_client, "get_signing_key_from_jwt", _raise)  # noqa: SLF001
    with pytest.raises(InvalidCredentialError):
        validator.validate(_token(private_key))


def test_https_only_jwks_url_is_enforced() -> None:
    """A non-HTTPS JWKS URL is rejected when resolving settings."""
    from backend.auth.oidc import build_oidc_settings
    from backend.config.settings import Settings

    settings = Settings(autodev_oidc_jwks_url="http://idp.example.com/jwks.json")
    with pytest.raises(ValueError, match="HTTPS"):
        build_oidc_settings(settings)


def test_pkce_challenge_is_s256_of_verifier() -> None:
    """The PKCE code challenge is the base64url-encoded SHA-256 of the verifier."""
    challenge = generate_pkce_challenge()
    digest = hashlib.sha256(challenge.code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert challenge.code_challenge == expected
    assert challenge.state
    assert challenge.code_verifier != challenge.code_challenge


def test_authorization_url_includes_pkce_and_state() -> None:
    """The authorization URL carries S256 PKCE parameters and the anti-CSRF state."""
    challenge = generate_pkce_challenge()
    url = build_authorization_url(
        _settings(),
        challenge=challenge,
        redirect_uri="https://app.example.com/v2/auth/oidc/callback",
    )
    assert "code_challenge_method=S256" in url
    assert f"state={challenge.state}" in url
    assert "response_type=code" in url
    assert url.startswith(f"{ISSUER}/authorize?")
