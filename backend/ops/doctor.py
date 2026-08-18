"""Preflight diagnostics for self-host bootstrap (E34-S2-T3).

``autodev doctor`` / :func:`run_diagnostics` runs a fixed set of typed,
actionable checks over the *current* environment: no daemon is started and
no migration is applied — every check is read-only or a best-effort
connectivity probe, so it is safe to run repeatedly and before
``autodev bootstrap``.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CheckStatus = Literal["ok", "fail"]


@dataclass(frozen=True)
class DiagnosticCheck:
    """One preflight diagnostic result.

    Attributes:
        name: Stable, machine-readable check identifier.
        status: ``"ok"`` or ``"fail"``.
        detail: Human-readable explanation, actionable on failure.
    """

    name: str
    status: CheckStatus
    detail: str

    def as_dict(self) -> dict[str, str]:
        """Return this check as a JSON-serializable dict."""
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _check_settings() -> DiagnosticCheck:
    """Verify declarative settings load cleanly under the active profile.

    ``Settings.validate_profile`` (a pydantic ``model_validator``) already
    fails closed on an inconsistent profile/storage combination — this
    check simply surfaces that as a typed diagnostic instead of an
    unhandled exception.
    """
    from backend.config.settings import get_settings

    try:
        settings = get_settings()
    except ValueError as exc:
        return DiagnosticCheck("settings", "fail", str(exc))
    return DiagnosticCheck(
        "settings",
        "ok",
        f"profile={settings.autodev_profile} storage_backend={settings.storage_backend}",
    )


def _check_port(host: str, port: int) -> DiagnosticCheck:
    """Verify the configured host:port is free to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        already_listening = sock.connect_ex((host, port)) == 0
    if already_listening:
        return DiagnosticCheck(
            "port",
            "fail",
            f"{host}:{port} is already in use (another autodev instance running?)",
        )
    return DiagnosticCheck("port", "ok", f"{host}:{port} is free")


def _check_project_root(project_root: str) -> DiagnosticCheck:
    """Verify the configured repository project root exists and is writable."""
    path = Path(project_root).expanduser()
    if not path.exists():
        return DiagnosticCheck("project_root", "fail", f"{path} does not exist")
    if not os.access(path, os.W_OK):
        return DiagnosticCheck("project_root", "fail", f"{path} is not writable")
    return DiagnosticCheck("project_root", "ok", f"{path} is writable")


def _resolve_sqlite_path(database_url: str) -> Path | None:
    """Return the filesystem path a ``sqlite://`` URL points at, or ``None``."""
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///")).expanduser()
    if database_url.startswith("sqlite://"):
        return Path(database_url.removeprefix("sqlite://")).expanduser()
    return None


def _check_database(database_url: str) -> DiagnosticCheck:
    """Verify the configured state store is reachable.

    SQLite: the parent directory of the database file must be writable
    (the file itself is created on first connect). PostgreSQL: a real,
    bounded-timeout connection attempt with ``SELECT 1``.
    """
    url = (database_url or "").strip()
    sqlite_path = _resolve_sqlite_path(url)
    if sqlite_path is not None:
        parent = sqlite_path.parent
        if not parent.exists() or not os.access(parent, os.W_OK):
            return DiagnosticCheck(
                "database", "fail", f"{parent} is not writable for the SQLite database file"
            )
        return DiagnosticCheck("database", "ok", f"sqlite at {sqlite_path}")

    if url.startswith("postgresql://") or url.startswith("postgres://"):
        try:
            import psycopg  # type: ignore[import-untyped]
        except ImportError:
            return DiagnosticCheck(
                "database", "fail", "postgresql:// configured but psycopg is not installed"
            )
        try:
            with psycopg.connect(url, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
        except Exception as exc:  # noqa: BLE001 - any connection failure is a typed check result
            return DiagnosticCheck("database", "fail", f"could not connect: {exc}")
        return DiagnosticCheck("database", "ok", "postgresql reachable")

    return DiagnosticCheck("database", "fail", f"unsupported DATABASE_URL scheme: {url!r}")


def _check_storage_backend(
    storage_backend: str, artifact_dir: str, minio_endpoint: str
) -> DiagnosticCheck:
    """Verify the configured artifact storage posture is reachable/writable."""
    if storage_backend == "local":
        path = Path(artifact_dir).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return DiagnosticCheck("storage_backend", "fail", f"cannot create {path}: {exc}")
        if not os.access(path, os.W_OK):
            return DiagnosticCheck("storage_backend", "fail", f"{path} is not writable")
        return DiagnosticCheck("storage_backend", "ok", f"local artifact dir {path} is writable")
    if storage_backend == "s3":
        if not minio_endpoint.strip():
            return DiagnosticCheck(
                "storage_backend",
                "fail",
                "storage_backend=s3 but AUTODEV_MINIO_ENDPOINT is unset",
            )
        return DiagnosticCheck(
            "storage_backend", "ok", f"s3 endpoint configured ({minio_endpoint})"
        )
    return DiagnosticCheck("storage_backend", "fail", f"unknown storage_backend: {storage_backend!r}")


def run_diagnostics() -> tuple[DiagnosticCheck, ...]:
    """Run every preflight diagnostic check against the current environment.

    Returns:
        Checks in a fixed order, always starting with ``settings``. When
        ``settings`` fails, the remaining checks (which need a valid
        settings object to know what to probe) are skipped rather than run
        against configuration already known to be invalid.
    """
    settings_check = _check_settings()
    checks = [settings_check]
    if settings_check.status != "ok":
        return tuple(checks)

    from backend.config import RuntimeConfigService
    from backend.config.settings import get_settings

    settings = get_settings()
    runtime_config = RuntimeConfigService().load()

    checks.append(
        _check_port(
            os.environ.get("AUTODEV_HOST", "127.0.0.1"),
            int(os.environ.get("AUTODEV_PORT", "8000")),
        )
    )
    checks.append(_check_project_root(runtime_config.repository.project_root))
    checks.append(_check_database(settings.database_url))
    checks.append(
        _check_storage_backend(
            settings.storage_backend, settings.autodev_artifact_dir, settings.autodev_minio_endpoint
        )
    )
    return tuple(checks)


def diagnostics_ok(checks: tuple[DiagnosticCheck, ...]) -> bool:
    """Return whether every check in *checks* passed."""
    return all(check.status == "ok" for check in checks)


__all__ = ["CheckStatus", "DiagnosticCheck", "diagnostics_ok", "run_diagnostics"]
