"""Process-local registry of terminal sessions (E65-S1-T3).

The key includes the project root, so a session of another project is
structurally unreachable rather than guarded by a check.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from backend.config.settings import Settings
from backend.terminal.session import TerminalSession

Key = tuple[str, str, str]


class TerminalCapError(Exception):
    """Raised when a tenant is at its concurrent-session cap."""


def terminal_enabled(settings: Settings | None = None) -> bool:
    """Whether the terminal may be used under *settings* (fail-closed).

    Args:
        settings: Settings to evaluate; defaults to a fresh ``Settings()``.

    Returns:
        ``True`` only when ``AUTODEV_ENABLE_TERMINAL`` is on and, under the
        ``prod`` profile, ``AUTODEV_TERMINAL_ALLOW_PROD`` is also on.
    """
    s = settings or Settings()
    if not s.autodev_enable_terminal:
        return False
    return s.autodev_profile != "prod" or s.autodev_terminal_allow_prod


class TerminalManager:
    """Holds sessions keyed by ``(tenant_id, project_root, terminal_id)``.

    Args:
        idle_ttl: Seconds of inactivity after which a session is reaped.
        max_per_tenant: Maximum concurrent sessions per tenant.
    """

    def __init__(self, idle_ttl: float = 1800.0, max_per_tenant: int = 4) -> None:
        self._sessions: dict[Key, TerminalSession] = {}
        self._lock = threading.Lock()
        self.idle_ttl = idle_ttl
        self.max_per_tenant = max_per_tenant

    def attach(self, tenant_id: str, project_root: Path, terminal_id: str) -> tuple[TerminalSession, bool]:
        """Return the live session for the key, creating one if needed.

        Args:
            tenant_id: Owning tenant.
            project_root: Project root; part of the key and the shell's cwd.
            terminal_id: Client-generated terminal id.

        Returns:
            ``(session, created)``.

        Raises:
            TerminalCapError: If a new session would exceed the tenant cap.
        """
        key: Key = (tenant_id, str(project_root), terminal_id)
        with self._lock:
            self._sweep_locked()
            existing = self._sessions.get(key)
            if existing is not None and existing.alive:
                existing.last_active = time.monotonic()
                return existing, False
            if existing is not None:
                self._sessions.pop(key).close()
            if sum(1 for k in self._sessions if k[0] == tenant_id) >= self.max_per_tenant:
                raise TerminalCapError("terminal session limit reached")
            session = TerminalSession(Path(project_root))
            self._sessions[key] = session
            return session, True

    def sweep(self) -> None:
        """Close dead and idle sessions."""
        with self._lock:
            self._sweep_locked()

    def _sweep_locked(self) -> None:
        now = time.monotonic()
        for key, session in list(self._sessions.items()):
            if not session.alive or now - session.last_active > self.idle_ttl:
                self._sessions.pop(key).close()

    def close_all(self) -> None:
        """Close every session."""
        with self._lock:
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()


_manager: TerminalManager | None = None


def get_terminal_manager() -> TerminalManager:
    """Return the process-wide manager."""
    global _manager
    if _manager is None:
        _manager = TerminalManager()
    return _manager
