"""One long-lived interactive shell on a host pseudo-terminal (E65-S1).

Output is never logged or redacted here; callers must not log it either
(the E33 redactor is not on this path).
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import select
import signal
import struct
import termios
import threading
import time
from collections.abc import Callable
from pathlib import Path

SCROLLBACK_BYTES = 64 * 1024
_ENV_ALLOWLIST = frozenset(
    {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SHELL", "TMPDIR"}
)
_READ_CHUNK = 4096


def build_session_env(source: dict[str, str] | None = None) -> dict[str, str]:
    """Return the allowlisted environment a terminal child starts with.

    Args:
        source: Environment to filter; defaults to ``os.environ``. Anything not
            allowlisted (including secrets injected by the secret store) is dropped.

    Returns:
        The filtered environment with ``TERM=xterm-256color`` set.
    """
    env = {k: v for k, v in (source if source is not None else os.environ).items() if k in _ENV_ALLOWLIST}
    env["TERM"] = "xterm-256color"
    return env


class TerminalSession:
    """A shell process attached to a PTY, with a reader thread and scrollback.

    Args:
        cwd: Directory the shell starts in (the project root).
        shell: Shell executable; defaults to ``$SHELL`` or ``/bin/sh``.
        env: Child environment; defaults to :func:`build_session_env`.
    """

    def __init__(self, cwd: Path, shell: str | None = None, env: dict[str, str] | None = None) -> None:
        self.cwd = Path(cwd)
        self.last_active = time.monotonic()
        self._lock = threading.Lock()
        self._scrollback = bytearray()
        self._listeners: list[Callable[[bytes], None]] = []
        self._exit_listeners: list[Callable[[int | None], None]] = []
        self._closed = False
        self.exit_code: int | None = None
        self.exited = threading.Event()
        shell_path = shell or os.environ.get("SHELL") or "/bin/sh"
        child_env = env if env is not None else build_session_env()
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - child process
            try:
                os.chdir(self.cwd)
                os.execve(shell_path, [shell_path, "-i"], child_env)
            finally:
                os._exit(127)
        self.pid = pid
        self._fd = fd
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    @property
    def alive(self) -> bool:
        """Whether the shell is still running."""
        return not self.exited.is_set()

    def scrollback(self) -> bytes:
        """Return the bounded recent output, for a reattaching client."""
        with self._lock:
            return bytes(self._scrollback)

    def subscribe(
        self,
        on_output: Callable[[bytes], None],
        on_exit: Callable[[int | None], None],
    ) -> Callable[[], None]:
        """Register output/exit callbacks (invoked on the reader thread).

        Args:
            on_output: Called with each output chunk.
            on_exit: Called once with the exit code when the shell ends.

        Returns:
            A function that unregisters both callbacks.
        """
        with self._lock:
            self._listeners.append(on_output)
            self._exit_listeners.append(on_exit)

        def unsubscribe() -> None:
            with self._lock:
                if on_output in self._listeners:
                    self._listeners.remove(on_output)
                if on_exit in self._exit_listeners:
                    self._exit_listeners.remove(on_exit)

        return unsubscribe

    def write(self, data: bytes) -> None:
        """Send input bytes to the shell (``\\x03`` raises SIGINT via the line discipline)."""
        self.last_active = time.monotonic()
        if self._closed or self.exited.is_set():
            return
        try:
            os.write(self._fd, data)
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        """Set the window size and notify the foreground process group."""
        if self._closed or self.exited.is_set():
            return
        cols, rows = max(1, min(cols, 1000)), max(1, min(rows, 1000))
        try:
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            os.kill(self.pid, signal.SIGWINCH)
        except OSError:
            pass

    def _read_loop(self) -> None:
        while not self._closed:
            try:
                ready, _, _ = select.select([self._fd], [], [], 0.2)
                if not ready:
                    if self._reap(block=False):
                        break
                    continue
                chunk = os.read(self._fd, _READ_CHUNK)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    break
                continue
            if not chunk:
                break
            with self._lock:
                self._scrollback += chunk
                del self._scrollback[:-SCROLLBACK_BYTES]
                listeners = list(self._listeners)
            for listener in listeners:
                try:
                    listener(chunk)
                except Exception:  # noqa: BLE001 - one bad listener must not kill the reader
                    pass
        self._reap(block=True)
        with self._lock:
            exit_listeners = list(self._exit_listeners)
        for exit_listener in exit_listeners:
            try:
                exit_listener(self.exit_code)
            except Exception:  # noqa: BLE001
                pass

    def _reap(self, *, block: bool) -> bool:
        """waitpid the child and record the exit code; True once reaped."""
        if self.exited.is_set():
            return True
        try:
            pid, status = os.waitpid(self.pid, 0 if block else os.WNOHANG)
        except ChildProcessError:
            pid, status = self.pid, 0
        if pid == 0:
            return False
        self.exit_code = os.waitstatus_to_exitcode(status)
        self.exited.set()
        return True

    def close(self, grace: float = 1.0) -> None:
        """Tear down: SIGHUP, grace, SIGKILL, reap, close the master fd (idempotent)."""
        if self._closed:
            return
        self._closed = True
        if not self.exited.is_set():
            for sig in (signal.SIGHUP, signal.SIGKILL):
                try:
                    os.kill(self.pid, sig)
                except OSError:
                    break
                deadline = time.monotonic() + grace
                while time.monotonic() < deadline:
                    if self._reap(block=False):
                        break
                    time.sleep(0.02)
                if self.exited.is_set():
                    break
            self._reap(block=True)
        self._reader.join(timeout=2.0)
        try:
            os.close(self._fd)
        except OSError:
            pass
