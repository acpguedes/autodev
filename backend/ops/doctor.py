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
from typing import Any, Literal

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


#: Minimum PostgreSQL major server version this codebase supports (E48-S3, ADR-024).
_MIN_POSTGRES_SERVER_MAJOR_VERSION = 16

#: Name of the HNSW index created by migration 4
#: (``backend/persistence/migrations/postgres_versions.py:_pg_m4_create_code_embeddings_table``).
_HNSW_INDEX_NAME = "idx_pg_code_embeddings_hnsw"


def _is_postgres_database_url(database_url: str) -> bool:
    """Return whether *database_url* addresses a PostgreSQL database."""
    url = (database_url or "").strip()
    return url.startswith("postgresql://") or url.startswith("postgres://")


def _check_postgres_server_version(conn: Any) -> DiagnosticCheck:
    """Verify the connected PostgreSQL server meets the minimum supported major version."""
    row = conn.execute("SHOW server_version_num").fetchone()
    version_num = int(row[0]) if row else 0
    major = version_num // 10000
    if major < _MIN_POSTGRES_SERVER_MAJOR_VERSION:
        return DiagnosticCheck(
            "postgres_server_version",
            "fail",
            f"server major version {major} is below the minimum supported "
            f"{_MIN_POSTGRES_SERVER_MAJOR_VERSION}",
        )
    return DiagnosticCheck("postgres_server_version", "ok", f"server major version {major}")


def _check_pgvector_extension_present(conn: Any) -> DiagnosticCheck:
    """Verify the ``vector`` extension is installed (ADR-024, E48-S2)."""
    row = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
    if row is None:
        return DiagnosticCheck(
            "pgvector_extension_present",
            "fail",
            "the 'vector' extension is not installed; ask a database operator with "
            "sufficient privilege to run: CREATE EXTENSION vector;",
        )
    return DiagnosticCheck("pgvector_extension_present", "ok", "vector extension installed")


def _check_pgvector_extension_usable(conn: Any) -> DiagnosticCheck:
    """Verify the ``vector`` type is usable by the connected role, not merely present.

    A provider offering a different pgvector version may have the extension
    catalog entry present but the type/operators unusable by this role — see
    ADR-024's "presence is not sufficient" decision.
    """
    try:
        conn.execute("SELECT '[1,2,3]'::vector")
    except Exception as exc:  # noqa: BLE001 - any usability failure is a typed check result
        return DiagnosticCheck(
            "pgvector_extension_usable", "fail", f"vector type is not usable by this role: {exc}"
        )
    return DiagnosticCheck("pgvector_extension_usable", "ok", "vector type is usable")


def _check_pgvector_hnsw_index(conn: Any) -> DiagnosticCheck:
    """Verify the HNSW index over ``code_embeddings.embedding`` exists and is valid."""
    try:
        row = conn.execute(
            f"SELECT indisvalid FROM pg_index WHERE indexrelid = '{_HNSW_INDEX_NAME}'::regclass"
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 - any lookup failure is a typed check result
        return DiagnosticCheck(
            "pgvector_hnsw_index", "fail", f"could not verify HNSW index {_HNSW_INDEX_NAME!r}: {exc}"
        )
    if row is None:
        return DiagnosticCheck(
            "pgvector_hnsw_index", "fail", f"HNSW index {_HNSW_INDEX_NAME!r} does not exist"
        )
    if not row[0]:
        return DiagnosticCheck(
            "pgvector_hnsw_index", "fail", f"HNSW index {_HNSW_INDEX_NAME!r} exists but is not valid"
        )
    return DiagnosticCheck("pgvector_hnsw_index", "ok", "HNSW index is valid")


def _pgvector_readiness_checks(database_url: str) -> list[DiagnosticCheck]:
    """Run the four pgvector-specific preflight checks against *database_url* (E48-S3).

    Only called for a PostgreSQL ``database_url`` whose connectivity
    (``database`` check) already succeeded. Opens exactly one connection and
    runs all four checks against it — one connection per startup, not one
    per check — closing it afterward. Each of the four conditions is
    reported independently even if an earlier one already failed: the
    connection is put in autocommit mode so a failing statement (e.g. an
    unusable ``vector`` type) cannot leave the implicit transaction aborted
    and poison the next check's result.
    """
    import psycopg  # type: ignore[import-untyped]

    try:
        conn = psycopg.connect(database_url, connect_timeout=3)
        conn.autocommit = True
    except Exception as exc:  # noqa: BLE001 - any connection failure is a typed check result
        detail = f"could not connect to check pgvector readiness: {exc}"
        return [
            DiagnosticCheck("postgres_server_version", "fail", detail),
            DiagnosticCheck("pgvector_extension_present", "fail", detail),
            DiagnosticCheck("pgvector_extension_usable", "fail", detail),
            DiagnosticCheck("pgvector_hnsw_index", "fail", detail),
        ]
    try:
        return [
            _check_postgres_server_version(conn),
            _check_pgvector_extension_present(conn),
            _check_pgvector_extension_usable(conn),
            _check_pgvector_hnsw_index(conn),
        ]
    finally:
        conn.close()


def _check_postgres_pool_health() -> DiagnosticCheck:
    """Reflect the live PostgreSQL connection pool's saturation in readiness (E60-S4-T2).

    Reads the process-wide store's own pool stats via
    :func:`~backend.persistence.database.get_cached_store` -- never
    constructing a pool as a side effect of a readiness probe -- because
    pool exhaustion is a client-side wait-queue condition a fresh probe
    connection could still open around; only the pool's own bookkeeping
    shows it, which is exactly why an orchestrator watching only request
    latency cannot see saturation coming.
    """
    from backend.persistence.database import get_cached_store

    store = get_cached_store()
    if store is None:
        return DiagnosticCheck("postgres_pool", "ok", "pool not yet initialized")
    pool_stats = getattr(store, "pool_stats", None)
    if pool_stats is None:
        return DiagnosticCheck("postgres_pool", "ok", "not applicable to this store")
    stats = pool_stats()
    available = stats.get("pool_available")
    waiting = stats.get("requests_waiting", 0)
    if available is not None and available <= 0 and waiting:
        return DiagnosticCheck(
            "postgres_pool",
            "fail",
            f"connection pool saturated: 0 connections available, {waiting} requests waiting",
        )
    return DiagnosticCheck("postgres_pool", "ok", f"available={available} waiting={waiting}")


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
    database_check = _check_database(settings.database_url)
    checks.append(database_check)
    if database_check.status == "ok" and _is_postgres_database_url(settings.database_url):
        checks.extend(_pgvector_readiness_checks(settings.database_url))
        checks.append(_check_postgres_pool_health())
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
