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
    """Build the namespaced cache key stored in the backend.

    Args:
        namespace: Logical cache namespace.
        key: Key within the namespace.

    Returns:
        The fully qualified cache key.
    """
    return f"autodev:cache:{namespace}:{key}"


def _lock_key(name: str) -> str:
    """Build the namespaced lock key stored in the backend.

    Args:
        name: Logical lock name.

    Returns:
        The fully qualified lock key.
    """
    return f"autodev:locks:{name}"


class LocalCache:
    """In-process cache used when no Redis backend is configured."""

    def __init__(self) -> None:
        """Initialize an empty, thread-safe in-memory cache."""
        self._values: dict[str, tuple[bytes, float | None]] = {}
        self._lock = threading.Lock()

    def set(self, namespace: str, key: str, value: bytes, *, ttl_seconds: float | None = None) -> None:
        """Store a value, optionally expiring after a TTL.

        Args:
            namespace: Logical cache namespace.
            key: Key within the namespace.
            value: Bytes to store.
            ttl_seconds: Time-to-live in seconds; ``None`` means no expiry.
        """
        expires_at = None if ttl_seconds is None else time.monotonic() + ttl_seconds
        with self._lock:
            self._values[_cache_key(namespace, key)] = (value, expires_at)

    def get(self, namespace: str, key: str) -> bytes | None:
        """Retrieve a stored value if present and not expired.

        Args:
            namespace: Logical cache namespace.
            key: Key within the namespace.

        Returns:
            The stored bytes, or ``None`` if absent or expired.
        """
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
        """Remove a stored value, if present.

        Args:
            namespace: Logical cache namespace.
            key: Key within the namespace.
        """
        with self._lock:
            self._values.pop(_cache_key(namespace, key), None)


class RedisCache:
    """Redis-backed cache."""

    def __init__(self, *, client: Any | None = None, url: str = "") -> None:
        """Initialize the cache, connecting to Redis and verifying reachability.

        Args:
            client: Pre-built Redis client to reuse; a new one is built if omitted.
            url: Redis connection URL, used when ``client`` is omitted.

        Raises:
            RuntimeError: If the ``redis`` package is not installed.
            ValueError: If ``client`` is omitted and ``url`` is blank.
        """
        if client is None:
            client = _redis_client_from_url(url)
        self._client = client
        self._client.ping()

    def set(self, namespace: str, key: str, value: bytes, *, ttl_seconds: float | None = None) -> None:
        """Store a value in Redis, optionally with an expiry.

        Args:
            namespace: Logical cache namespace.
            key: Key within the namespace.
            value: Bytes to store.
            ttl_seconds: Time-to-live in seconds; ``None`` means no expiry.
        """
        kwargs: dict[str, int] = {}
        if ttl_seconds is not None:
            kwargs["px"] = max(1, int(ttl_seconds * 1000))
        self._client.set(_cache_key(namespace, key), value, **kwargs)

    def get(self, namespace: str, key: str) -> bytes | None:
        """Retrieve a stored value from Redis.

        Args:
            namespace: Logical cache namespace.
            key: Key within the namespace.

        Returns:
            The stored bytes, or ``None`` if absent.
        """
        return self._client.get(_cache_key(namespace, key))

    def delete(self, namespace: str, key: str) -> None:
        """Remove a stored value from Redis, if present.

        Args:
            namespace: Logical cache namespace.
            key: Key within the namespace.
        """
        self._client.delete(_cache_key(namespace, key))


@dataclass
class LocalLockLease:
    """An in-process, token-guarded lease on a named local lock.

    Attributes:
        name: Namespaced lock key.
        ttl_seconds: Default lease duration in seconds.
        token: Unique token identifying this lease's ownership.
    """

    name: str
    ttl_seconds: float
    _state: dict[str, tuple[str, float]]
    _mutex: threading.Lock
    token: str = field(default_factory=lambda: str(uuid.uuid4()))

    def acquire(self) -> bool:
        """Attempt to acquire the lock if it is free or expired.

        Returns:
            ``True`` if the lock was acquired, ``False`` if already held.
        """
        now = time.monotonic()
        with self._mutex:
            current = self._state.get(self.name)
            if current is not None and current[1] > now:
                return False
            self._state[self.name] = (self.token, now + self.ttl_seconds)
            return True

    def renew(self, *, ttl_seconds: float | None = None) -> bool:
        """Extend the lease's expiry if this lease still owns the lock.

        Args:
            ttl_seconds: New lease duration in seconds; defaults to the original TTL.

        Returns:
            ``True`` if the lease was renewed, ``False`` if it no longer owns the lock.
        """
        with self._mutex:
            current = self._state.get(self.name)
            if current is None or current[0] != self.token:
                return False
            self._state[self.name] = (self.token, time.monotonic() + (ttl_seconds or self.ttl_seconds))
            return True

    def release(self) -> bool:
        """Release the lock if this lease still owns it.

        Returns:
            ``True`` if the lock was released, ``False`` if it no longer owns the lock.
        """
        with self._mutex:
            current = self._state.get(self.name)
            if current is None or current[0] != self.token:
                return False
            self._state.pop(self.name, None)
            return True


class LocalLockManager:
    """In-process lock manager used when no Redis backend is configured."""

    def __init__(self) -> None:
        """Initialize an empty, thread-safe local lock table."""
        self._state: dict[str, tuple[str, float]] = {}
        self._mutex = threading.Lock()

    def lock(self, name: str, *, ttl_seconds: float) -> LocalLockLease:
        """Build a lease object for a named lock.

        Args:
            name: Logical lock name.
            ttl_seconds: Default lease duration in seconds.

        Returns:
            A new, unacquired :class:`LocalLockLease`.
        """
        return LocalLockLease(
            name=_lock_key(name),
            ttl_seconds=ttl_seconds,
            _state=self._state,
            _mutex=self._mutex,
        )


@dataclass
class RedisLockLease:
    """A Redis-backed, token-guarded lease on a named distributed lock.

    Attributes:
        name: Logical lock name.
        ttl_seconds: Default lease duration in seconds.
        client: Redis client used to manipulate the lock key.
        token: Unique token identifying this lease's ownership.
    """

    name: str
    ttl_seconds: float
    client: Any
    token: str = field(default_factory=lambda: str(uuid.uuid4()))

    def acquire(self) -> bool:
        """Attempt to atomically acquire the lock via ``SET NX PX``.

        Returns:
            ``True`` if the lock was acquired, ``False`` if already held.
        """
        return bool(
            self.client.set(
                _lock_key(self.name),
                self.token,
                nx=True,
                px=max(1, int(self.ttl_seconds * 1000)),
            )
        )

    def renew(self, *, ttl_seconds: float | None = None) -> bool:
        """Extend the lease's expiry if this lease still owns the lock.

        Args:
            ttl_seconds: New lease duration in seconds; defaults to the original TTL.

        Returns:
            ``True`` if the lease was renewed, ``False`` if it no longer owns the lock.
        """
        ttl_ms = max(1, int((ttl_seconds or self.ttl_seconds) * 1000))
        return bool(self.client.eval(_RENEW_SCRIPT, 1, _lock_key(self.name), self.token, ttl_ms))

    def release(self) -> bool:
        """Release the lock if this lease still owns it.

        Returns:
            ``True`` if the lock was released, ``False`` if it no longer owns the lock.
        """
        return bool(self.client.eval(_RELEASE_SCRIPT, 1, _lock_key(self.name), self.token))


class RedisLockManager:
    """Distributed lock manager backed by Redis."""

    def __init__(self, *, client: Any | None = None, url: str = "") -> None:
        """Initialize the manager, connecting to Redis and verifying reachability.

        Args:
            client: Pre-built Redis client to reuse; a new one is built if omitted.
            url: Redis connection URL, used when ``client`` is omitted.

        Raises:
            RuntimeError: If the ``redis`` package is not installed.
            ValueError: If ``client`` is omitted and ``url`` is blank.
        """
        if client is None:
            client = _redis_client_from_url(url)
        self._client = client
        self._client.ping()

    def lock(self, name: str, *, ttl_seconds: float) -> RedisLockLease:
        """Build a lease object for a named distributed lock.

        Args:
            name: Logical lock name.
            ttl_seconds: Default lease duration in seconds.

        Returns:
            A new, unacquired :class:`RedisLockLease`.
        """
        return RedisLockLease(name=name, ttl_seconds=ttl_seconds, client=self._client)


def _redis_client_from_url(url: str) -> Any:
    """Build a Redis client from a connection URL.

    Args:
        url: Redis connection URL.

    Returns:
        A connected Redis client.

    Raises:
        RuntimeError: If the ``redis`` package is not installed.
        ValueError: If ``url`` is blank.
    """
    try:
        import redis  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("redis package is not installed.") from exc
    if not url.strip():
        raise ValueError("Redis URL is required")
    return redis.from_url(url)


def get_cache(settings: Settings | None = None) -> LocalCache | RedisCache:
    """Build the configured cache backend.

    Args:
        settings: Settings override; falls back to :func:`get_settings`.

    Returns:
        A :class:`RedisCache` if ``autodev_job_backend`` is ``"redis"``, else :class:`LocalCache`.
    """
    active = settings or get_settings()
    if active.autodev_job_backend == "redis":
        return RedisCache(url=active.autodev_redis_url)
    return LocalCache()


def get_lock_manager(settings: Settings | None = None) -> LocalLockManager | RedisLockManager:
    """Build the configured lock manager backend.

    Args:
        settings: Settings override; falls back to :func:`get_settings`.

    Returns:
        A :class:`RedisLockManager` if ``autodev_job_backend`` is ``"redis"``, else
        :class:`LocalLockManager`.
    """
    active = settings or get_settings()
    if active.autodev_job_backend == "redis":
        return RedisLockManager(url=active.autodev_redis_url)
    return LocalLockManager()
