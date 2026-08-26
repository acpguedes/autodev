"""Fail-vs-skip gating for tests that need a real external service (E57).

A PostgreSQL/MinIO variant is cheap to skip when nothing set
``AUTODEV_TEST_POSTGRES_URL``/``AUTODEV_TEST_MINIO_ENDPOINT`` -- outside CI,
or on CI's SQLite-only leg, that is a normal, explicitly-named skip. On
CI's PostgreSQL/MinIO leg the same missing-service condition must instead
fail the run: a broken service container has to turn that leg red, not
quietly skip its own proof (E57-S2-T2). ``AUTODEV_REQUIRE_POSTGRES`` /
``AUTODEV_REQUIRE_MINIO`` (set only on that leg) select which behavior
applies.
"""

from __future__ import annotations

import os

import pytest

POSTGRES_URL_ENV = "AUTODEV_TEST_POSTGRES_URL"
REQUIRE_POSTGRES_ENV = "AUTODEV_REQUIRE_POSTGRES"
MINIO_ENDPOINT_ENV = "AUTODEV_TEST_MINIO_ENDPOINT"
REQUIRE_MINIO_ENV = "AUTODEV_REQUIRE_MINIO"


def postgres_url() -> str:
    """Return the configured PostgreSQL admin URL, or ``""`` if unset."""
    return os.environ.get(POSTGRES_URL_ENV, "")


def minio_endpoint() -> str:
    """Return the configured MinIO endpoint, or ``""`` if unset."""
    return os.environ.get(MINIO_ENDPOINT_ENV, "")


def require_mark(available: bool, *, require_env: str, reason: str) -> pytest.MarkDecorator:
    """A ``skipif`` mark for *reason*, or a hard collection-time failure.

    Args:
        available: Whether the service this test needs is configured.
        require_env: Name of the env var that turns "skip" into "fail" --
            set only on the CI leg that must not silently skip.
        reason: Human-readable reason, used for both the skip message and
            the failure message.

    Returns:
        A no-op ``skipif`` mark when *available*; otherwise a ``skipif(True,
        ...)`` mark, unless *require_env* is set, in which case this raises
        immediately (surfacing as a collection error for the importing
        module) instead of returning.
    """
    if available:
        return pytest.mark.skipif(False, reason=reason)
    if os.environ.get(require_env):
        raise RuntimeError(reason)
    return pytest.mark.skipif(True, reason=reason)
