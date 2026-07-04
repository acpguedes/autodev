"""Redis-backed cache and lock primitives with local fallbacks."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any
import uuid

from backend.config.settings import Settings, get_settings


_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""

_RENEW_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("pexpire", KEYS[1], ARGV[2])
end
return 0
"""


def _cache_key(namespace: str, key: str) -> str:
    return f"autodev:cache:{namespace}:{key}"


def _lock_key(name: str) -> str:
    return f"autodev:locks:{name}"


class LocalCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[bytes, float | None]] = {}
        self._lock = threading.Lock()

    def set(self, namespace: str, key: str, value: bytes, *, ttl_seconds: float | None = None) -> None:
        expires_at = None if ttl_seconds is None else time.monotonic() + ttl_seconds
        with self._lock:
            self._values[_cache_key(namespace, key)] = (value, expires_at)

    def get(self, namespace: str, key: str) -> bytes | None:
        namespaced = _cache_key(namespace, key)
        with self._lock:
            record = self._values.get(namespaced)
            if record is None:
                return None
            value, expires_at = record
            if expires_at is not None and expires_at <= time.monotonic():
                self._values.pop(namespaced, None)
                return None
            return value

    def delete(self, namespace: str, key: str) -> None:
        with self._lock:
            self._values.pop(_cache_key(namespace, key), None)


class RedisCache:
    def __init__(self, *, client: Any | None = None, url: str = "") -> None:
        if client is None:
            client = _redis_client_from_url(url)
        self._client = client
        self._client.ping()

    def set(self, namespace: str, key: str, value: bytes, *, ttl_seconds: float | None = None) -> None:
        kwargs: dict[str, int] = {}
        if ttl_seconds is not None:
            kwargs["px"] = max(1, int(ttl_seconds * 1000))
        self._client.set(_cache_key(namespace, key), value, **kwargs)

    def get(self, namespace: str, key: str) -> bytes | None:
        return self._client.get(_cache_key(namespace, key))

    def delete(self, namespace: str, key: str) -> None:
        self._client.delete(_cache_key(namespace, key))


@dataclass
class LocalLockLease:
    name: str
    ttl_seconds: float
    _state: dict[str, tuple[str, float]]
    _mutex: threading.Lock
    token: str = field(default_factory=lambda: str(uuid.uuid4()))

    def acquire(self) -> bool:
        now = time.monotonic()
        with self._mutex:
            current = self._state.get(self.name)
            if current is not None and current[1] > now:
                return False
            self._state[self.name] = (self.token, now + self.ttl_seconds)
            return True

    def renew(self, *, ttl_seconds: float | None = None) -> bool:
        with self._mutex:
            current = self._state.get(self.name)
            if current is None or current[0] != self.token:
                return False
            self._state[self.name] = (self.token, time.monotonic() + (ttl_seconds or self.ttl_seconds))
            return True

    def release(self) -> bool:
        with self._mutex:
            current = self._state.get(self.name)
            if current is None or current[0] != self.token:
                return False
            self._state.pop(self.name, None)
            return True


class LocalLockManager:
    def __init__(self) -> None:
        self._state: dict[str, tuple[str, float]] = {}
        self._mutex = threading.Lock()

    def lock(self, name: str, *, ttl_seconds: float) -> LocalLockLease:
        return LocalLockLease(
            name=_lock_key(name),
            ttl_seconds=ttl_seconds,
            _state=self._state,
            _mutex=self._mutex,
        )


@dataclass
class RedisLockLease:
    name: str
    ttl_seconds: float
    client: Any
    token: str = field(default_factory=lambda: str(uuid.uuid4()))

    def acquire(self) -> bool:
        return bool(
            self.client.set(
                _lock_key(self.name),
                self.token,
                nx=True,
                px=max(1, int(self.ttl_seconds * 1000)),
            )
        )

    def renew(self, *, ttl_seconds: float | None = None) -> bool:
        ttl_ms = max(1, int((ttl_seconds or self.ttl_seconds) * 1000))
        return bool(self.client.eval(_RENEW_SCRIPT, 1, _lock_key(self.name), self.token, ttl_ms))

    def release(self) -> bool:
        return bool(self.client.eval(_RELEASE_SCRIPT, 1, _lock_key(self.name), self.token))


class RedisLockManager:
    def __init__(self, *, client: Any | None = None, url: str = "") -> None:
        if client is None:
            client = _redis_client_from_url(url)
        self._client = client
        self._client.ping()

    def lock(self, name: str, *, ttl_seconds: float) -> RedisLockLease:
        return RedisLockLease(name=name, ttl_seconds=ttl_seconds, client=self._client)


def _redis_client_from_url(url: str) -> Any:
    try:
        import redis  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("redis package is not installed.") from exc
    if not url.strip():
        raise ValueError("Redis URL is required")
    return redis.from_url(url)


def get_cache(settings: Settings | None = None) -> LocalCache | RedisCache:
    active = settings or get_settings()
    if active.autodev_job_backend == "redis":
        return RedisCache(url=active.autodev_redis_url)
    return LocalCache()


def get_lock_manager(settings: Settings | None = None) -> LocalLockManager | RedisLockManager:
    active = settings or get_settings()
    if active.autodev_job_backend == "redis":
        return RedisLockManager(url=active.autodev_redis_url)
    return LocalLockManager()
