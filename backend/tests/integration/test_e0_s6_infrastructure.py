"""Infrastructure contract checks for E0-S6."""

from __future__ import annotations

from pathlib import Path


def test_prod_like_compose_profile_includes_redis_minio_and_backend_wiring() -> None:
    """The prod-like compose profile wires Redis and MinIO with the expected env vars."""
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


def test_compose_carries_no_production_default_credentials() -> None:
    """Compose never bakes in a fallback PostgreSQL or MinIO credential (E11-S4)."""
    compose = Path("infrastructure/docker-compose.yml").read_text()

    assert "postgresql://autodev:autodev@" not in compose
    assert "POSTGRES_PASSWORD: autodev" not in compose
    assert "minioadmin" not in compose
    assert "${AUTODEV_POSTGRES_PASSWORD:-}" in compose
    assert 'AUTODEV_MINIO_ACCESS_KEY: "${AUTODEV_MINIO_ACCESS_KEY:-}"' in compose
    assert 'AUTODEV_MINIO_SECRET_KEY: "${AUTODEV_MINIO_SECRET_KEY:-}"' in compose
    assert 'MINIO_ROOT_USER: "${AUTODEV_MINIO_ACCESS_KEY:-}"' in compose
    assert 'MINIO_ROOT_PASSWORD: "${AUTODEV_MINIO_SECRET_KEY:-}"' in compose
