"""Infrastructure contract checks for E0-S6."""

from __future__ import annotations

from pathlib import Path


def test_prod_like_compose_profile_includes_redis_minio_and_backend_wiring() -> None:
    compose = Path("infrastructure/docker-compose.yml").read_text()

    assert "redis:" in compose
    assert 'profiles: ["prod", "redis"]' in compose
    assert "redis:7-alpine" in compose
    assert "minio:" in compose
    assert 'profiles: ["prod", "minio"]' in compose
    assert "minio/minio:" in compose
    assert "AUTODEV_JOB_BACKEND: redis" in compose
    assert "AUTODEV_REDIS_URL: redis://redis:6379/0" in compose
    assert "STORAGE_BACKEND: s3" in compose
    assert "AUTODEV_MINIO_ENDPOINT: minio:9000" in compose
