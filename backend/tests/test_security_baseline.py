"""Security-baseline tests for HTTP headers and secret scanning."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from backend.api.security_headers import SecurityHeadersMiddleware
from backend.config.settings import reset_settings_cache
from backend.security.secrets import scan_path


def _middleware_headers() -> dict[str, str]:
    async def app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    messages: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    middleware = SecurityHeadersMiddleware(app)
    asyncio.run(middleware({"type": "http", "method": "GET", "path": "/health"}, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    raw_headers = cast(list[tuple[bytes, bytes]], start["headers"])
    return {
        key.decode("latin1"): value.decode("latin1")
        for key, value in raw_headers
    }


def test_default_security_headers_are_set(monkeypatch) -> None:
    monkeypatch.delenv("AUTODEV_API_TOKEN", raising=False)
    monkeypatch.delenv("AUTODEV_ENABLE_HSTS", raising=False)
    reset_settings_cache()

    headers = _middleware_headers()

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "strict-transport-security" not in headers


def test_hsts_header_is_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_HSTS", "true")
    reset_settings_cache()

    headers = _middleware_headers()

    assert headers["strict-transport-security"].startswith("max-age=31536000")


def test_secret_scanner_detects_high_confidence_secret(tmp_path: Path) -> None:
    config = tmp_path / ".env"
    config.write_text("OPENAI_API_KEY=sk-" + ("A" * 32) + "\n")

    findings = scan_path(tmp_path)

    assert len(findings) == 1
    assert findings[0].kind == "openai_api_key"
    assert findings[0].path == config


def test_secret_scanner_ignores_dummy_short_values(tmp_path: Path) -> None:
    config = tmp_path / "example.env"
    config.write_text("OPENAI_API_KEY=sk-super-secret\nAUTODEV_API_TOKEN=s3cret\n")

    assert scan_path(tmp_path) == []
