"""Optional bearer-token authentication for the control-plane API.

Authentication is *opt-in*: when the ``AUTODEV_API_TOKEN`` environment variable
is empty or unset the API stays fully open (preserving the local-first,
zero-config developer experience and the existing test suite). Once a token is
configured, every request must carry ``Authorization: Bearer <token>`` — except
unauthenticated liveness probes (``/health``) and the OpenAPI/docs endpoints,
which remain reachable so orchestration health checks keep working.

The token comparison uses :func:`hmac.compare_digest` to avoid leaking the
secret through timing side-channels.
"""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

# Paths that must stay reachable without a token so health checks and API
# discovery continue to work when authentication is enabled.
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {"/health", "/docs", "/redoc", "/openapi.json"}
)

_BEARER_PREFIX = "bearer "


def _configured_token() -> str:
    return os.getenv("AUTODEV_API_TOKEN", "").strip()


def require_api_token(request: Request) -> None:
    """FastAPI dependency enforcing bearer-token auth when configured.

    No-op when ``AUTODEV_API_TOKEN`` is unset/empty. Raises ``401`` when a token
    is configured but the request lacks a valid ``Authorization`` header.
    """

    token = _configured_token()
    if not token:
        return

    if request.url.path in _PUBLIC_PATHS:
        return

    header = request.headers.get("Authorization", "")
    if header[: len(_BEARER_PREFIX)].lower() != _BEARER_PREFIX:
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    presented = header[len(_BEARER_PREFIX) :].strip()
    if not hmac.compare_digest(presented, token):
        raise HTTPException(
            status_code=401,
            detail="Invalid API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


__all__ = ["require_api_token"]
