"""Tests for E0-S6 Redis/local cache and lock coordination."""

from __future__ import annotations

import time

from backend.coordination.redis import (
    LocalCache,
    LocalLockManager,
    RedisCache,
    RedisLockManager,
)


def test_local_lock_contention_prevents_duplicate_execution() -> None:
    """A second lease cannot acquire a lock already held, until it is released."""
    manager = LocalLockManager()

    first = manager.lock("workspace/repo", ttl_seconds=30)
    second = manager.lock("workspace/repo", ttl_seconds=30)

    assert first.acquire() is True
    assert second.acquire() is False

    first.release()
    assert second.acquire() is True


def test_local_lock_can_renew_before_timeout() -> None:
    """A held lease can renew its expiry before releasing."""
    manager = LocalLockManager()
    lease = manager.lock("workspace/repo", ttl_seconds=1)

    assert lease.acquire() is True
    assert lease.renew(ttl_seconds=5) is True
    assert lease.release() is True


def test_local_cache_roundtrip_and_expiry() -> None:
    """A cached value round-trips until its TTL elapses, then reads as missing."""
    cache = LocalCache()

    cache.set("registry", "agents", b"payload", ttl_seconds=0.01)
    assert cache.get("registry", "agents") == b"payload"
    time.sleep(0.02)
    assert cache.get("registry", "agents") is None


class _FakeRedis:
    """In-memory stand-in for a Redis client, used to test the Redis-backed cache and locks."""

    def __init__(self) -> None:
        """Initialize empty in-memory values and expiry tables."""
        self.values: dict[str, bytes] = {}
        self.expiry: dict[str, float] = {}

    def ping(self) -> bool:
        """Report the fake connection as always reachable."""
        return True

    def set(self, key: str, value: bytes | str, nx: bool = False, px: int | None = None, ex: int | None = None) -> bool:
        """Set a key's value, honoring ``nx`` (set-if-absent) and ``px``/``ex`` expiry."""
        if nx and self.get(key) is not None:
            return False
        self.values[key] = value.encode() if isinstance(value, str) else value
        if px is not None:
            self.expiry[key] = time.monotonic() + (px / 1000)
        elif ex is not None:
            self.expiry[key] = time.monotonic() + ex
        return True

    def get(self, key: str) -> bytes | None:
        """Return a key's value, or ``None`` if absent or expired."""
        expires_at = self.expiry.get(key)
        if expires_at is not None and expires_at <= time.monotonic():
            self.values.pop(key, None)
            self.expiry.pop(key, None)
            return None
        return self.values.get(key)

    def delete(self, key: str) -> int:
        """Delete a key, returning 1 if it existed, 0 otherwise."""
        existed = key in self.values
        self.values.pop(key, None)
        self.expiry.pop(key, None)
        return int(existed)

    def pexpire(self, key: str, milliseconds: int) -> int:
        """Set a key's expiry in milliseconds from now, if it currently exists."""
        if self.get(key) is None:
            return 0
        self.expiry[key] = time.monotonic() + (milliseconds / 1000)
        return 1

    def eval(self, script: str, numkeys: int, key: str, token: str, *args: object) -> int:
        """Emulate the release/renew Lua scripts by dispatching on script content."""
        if self.get(key) != token.encode():
            return 0
        if "pexpire" in script.lower():
            ttl_ms = args[0]
            assert isinstance(ttl_ms, int)
            return self.pexpire(key, ttl_ms)
        return self.delete(key)


def test_redis_lock_uses_namespaced_keys_and_token_checked_release() -> None:
    """Redis locks use namespaced keys and only release when the token matches."""
    client = _FakeRedis()
    manager = RedisLockManager(client=client)

    first = manager.lock("workspace/repo", ttl_seconds=30)
    second = manager.lock("workspace/repo", ttl_seconds=30)

    assert first.acquire() is True
    assert second.acquire() is False
    assert "autodev:locks:workspace/repo" in client.values
    assert second.release() is False
    assert first.release() is True


def test_redis_cache_uses_namespaced_keys() -> None:
    """The Redis cache stores values under namespaced keys."""
    client = _FakeRedis()
    cache = RedisCache(client=client)

    cache.set("registry", "agents", b"payload", ttl_seconds=30)

    assert client.values["autodev:cache:registry:agents"] == b"payload"
    assert cache.get("registry", "agents") == b"payload"
