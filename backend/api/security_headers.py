"""Default HTTP security headers for the control-plane API."""

from __future__ import annotations

from typing import Callable

from backend.config.settings import Settings


DEFAULT_SECURITY_HEADERS = {
    "content-security-policy": "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}

HSTS_HEADER = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    """ASGI middleware that appends conservative browser security headers."""

    def __init__(self, app: Callable) -> None:
        """Wrap an ASGI application with security-header injection.

        Args:
            app: The wrapped ASGI application callable.
        """
        self._app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Invoke the wrapped ASGI app, injecting security headers into HTTP responses.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel.
        """
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: dict) -> None:
            """Inject default security headers into the response-start ASGI message."""
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.decode("latin1").lower() for name, _ in headers}
                for name, value in DEFAULT_SECURITY_HEADERS.items():
                    if name not in present:
                        headers.append((name.encode("latin1"), value.encode("latin1")))
                if Settings().autodev_enable_hsts and "strict-transport-security" not in present:
                    headers.append((b"strict-transport-security", HSTS_HEADER.encode("latin1")))
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, send_with_headers)


__all__ = ["DEFAULT_SECURITY_HEADERS", "HSTS_HEADER", "SecurityHeadersMiddleware"]
