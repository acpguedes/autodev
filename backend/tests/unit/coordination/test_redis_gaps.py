"""Unit tests filling coverage gaps in ``backend/coordination/redis.py``.

Complements ``backend/tests/test_redis_coordination.py`` (not modified here)
by exercising: ``LocalLockLease.renew``/``.release`` failure paths,
``LocalCache.delete``, ``RedisCache.delete``, ``RedisCache.get`` for a
missing key, ``RedisLockLease.renew``, the ``get_cache()``/
``get_lock_manager()`` factories for both backends, and
``_redis_client_from_url``'s blank-URL guard.

A fake, in-memory Redis client is used throughout — no live Redis service or
network access is required.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from backend.config.settings import Settings
from backend.coordination.redis import (
    LocalCache,
    LocalLockManager,
    RedisCache,
    RedisLockManager,
    _redis_client_from_url,
    get_cache,
    get_lock_manager,
)


class _FakeRedis:
    """In-memory stand-in for a Redis client, used to test the Redis-backed cache and locks."""

    def __init__(self) -> None:
        """Initialize empty in-memory values and expiry tables."""
        self.values: dict[str, bytes] = {}
        self.expiry: dict[str, float] = {}

    def ping(self) -> bool:
        """Report the fake connection as always reachable."""
        return True

    def set(
        self,
        key: str,
        value: bytes | str,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool:
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


# ---------------------------------------------------------------------------
# LocalLockLease — renew/release failure paths
# ---------------------------------------------------------------------------


def test_local_lock_renew_fails_when_not_acquired() -> None:
    """Renewing a lease that never acquired the lock returns ``False``."""
    manager = LocalLockManager()
    lease = manager.lock("workspace/repo", ttl_seconds=30)

    assert lease.renew() is False


def test_local_lock_renew_fails_when_another_lease_holds_it() -> None:
    """Renewing a lease whose token no longer matches the current holder returns ``False``."""
    manager = LocalLockManager()
    first = manager.lock("workspace/repo", ttl_seconds=30)
    second = manager.lock("workspace/repo", ttl_seconds=30)

    assert first.acquire() is True
    assert second.renew() is False


def test_local_lock_release_fails_when_not_acquired() -> None:
    """Releasing a lease that never acquired the lock returns ``False``."""
    manager = LocalLockManager()
    lease = manager.lock("workspace/repo", ttl_seconds=30)

    assert lease.release() is False


def test_local_lock_release_fails_when_another_lease_holds_it() -> None:
    """Releasing a lease whose token no longer matches the current holder returns ``False``."""
    manager = LocalLockManager()
    first = manager.lock("workspace/repo", ttl_seconds=30)
    second = manager.lock("workspace/repo", ttl_seconds=30)

    assert first.acquire() is True
    assert second.release() is False
    assert first.release() is True


# ---------------------------------------------------------------------------
# LocalCache.delete
# ---------------------------------------------------------------------------


def test_local_cache_delete_removes_value() -> None:
    """Deleting a cached value makes subsequent reads return ``None``."""
    cache = LocalCache()
    cache.set("registry", "agents", b"payload")

    cache.delete("registry", "agents")

    assert cache.get("registry", "agents") is None


def test_local_cache_delete_missing_key_is_a_noop() -> None:
    """Deleting a key that was never set does not raise."""
    cache = LocalCache()

    cache.delete("registry", "does-not-exist")


# ---------------------------------------------------------------------------
# RedisCache — delete / missing-key get
# ---------------------------------------------------------------------------


def test_redis_cache_get_missing_key_returns_none() -> None:
    """Reading a key that was never set from the Redis cache returns ``None``."""
    cache = RedisCache(client=_FakeRedis())

    assert cache.get("registry", "agents") is None


def test_redis_cache_delete_removes_namespaced_key() -> None:
    """Deleting a Redis-cached value removes it under its namespaced key."""
    client = _FakeRedis()
    cache = RedisCache(client=client)
    cache.set("registry", "agents", b"payload")

    cache.delete("registry", "agents")

    assert "autodev:cache:registry:agents" not in client.values
    assert cache.get("registry", "agents") is None


# ---------------------------------------------------------------------------
# RedisLockLease.renew
# ---------------------------------------------------------------------------


def test_redis_lock_renew_succeeds_for_current_holder() -> None:
    """The current lease holder can renew its lock's expiry."""
    client = _FakeRedis()
    manager = RedisLockManager(client=client)
    lease = manager.lock("workspace/repo", ttl_seconds=30)

    assert lease.acquire() is True
    assert lease.renew(ttl_seconds=60) is True


def test_redis_lock_renew_fails_for_non_holder() -> None:
    """A lease that never acquired the lock cannot renew it."""
    client = _FakeRedis()
    manager = RedisLockManager(client=client)
    first = manager.lock("workspace/repo", ttl_seconds=30)
    second = manager.lock("workspace/repo", ttl_seconds=30)

    assert first.acquire() is True
    assert second.renew() is False


# ---------------------------------------------------------------------------
# get_cache() / get_lock_manager() factories
# ---------------------------------------------------------------------------


def test_get_cache_defaults_to_local() -> None:
    """``get_cache`` returns a :class:`LocalCache` for the ``inprocess`` backend."""
    settings = Settings(autodev_job_backend="inprocess")

    assert isinstance(get_cache(settings), LocalCache)


def test_get_cache_selects_redis_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_cache`` selects :class:`RedisCache` for the ``redis`` backend.

    The real class is monkeypatched out so only branch selection is under
    test, never a live Redis connection.
    """
    captured: dict[str, Any] = {}

    class _FakeRedisCache:
        """Stand-in for :class:`RedisCache` capturing the URL it was built with."""

        def __init__(self, *, url: str = "", **_kwargs: Any) -> None:
            """Record the connection URL passed by the factory."""
            captured["url"] = url

    monkeypatch.setattr("backend.coordination.redis.RedisCache", _FakeRedisCache)
    settings = Settings(autodev_job_backend="redis", autodev_redis_url="redis://example:6379/2")

    cache = get_cache(settings)

    assert isinstance(cache, _FakeRedisCache)
    assert captured["url"] == "redis://example:6379/2"


def test_get_lock_manager_defaults_to_local() -> None:
    """``get_lock_manager`` returns a :class:`LocalLockManager` for the ``inprocess`` backend."""
    settings = Settings(autodev_job_backend="inprocess")

    assert isinstance(get_lock_manager(settings), LocalLockManager)


def test_get_lock_manager_selects_redis_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_lock_manager`` selects :class:`RedisLockManager` for the ``redis`` backend.

    The real class is monkeypatched out so only branch selection is under
    test, never a live Redis connection.
    """
    captured: dict[str, Any] = {}

    class _FakeRedisLockManager:
        """Stand-in for :class:`RedisLockManager` capturing the URL it was built with."""

        def __init__(self, *, url: str = "", **_kwargs: Any) -> None:
            """Record the connection URL passed by the factory."""
            captured["url"] = url

    monkeypatch.setattr("backend.coordination.redis.RedisLockManager", _FakeRedisLockManager)
    settings = Settings(autodev_job_backend="redis", autodev_redis_url="redis://example:6379/3")

    manager = get_lock_manager(settings)

    assert isinstance(manager, _FakeRedisLockManager)
    assert captured["url"] == "redis://example:6379/3"


# ---------------------------------------------------------------------------
# _redis_client_from_url
# ---------------------------------------------------------------------------


def test_redis_client_from_url_rejects_blank_url() -> None:
    """Building a client from a blank URL raises ``ValueError``."""
    with pytest.raises(ValueError, match="Redis URL is required"):
        _redis_client_from_url("   ")
