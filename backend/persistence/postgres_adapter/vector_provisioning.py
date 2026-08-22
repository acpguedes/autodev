"""Extension provisioning for the pgvector ``vector`` type (E48-S2, ADR-024).

Separated from schema migration (``backend/persistence/migrations/postgres_versions.py``)
so that schema migration no longer requires ``CREATE EXTENSION`` privilege.
Managed PostgreSQL providers frequently grant the application role no such
privilege even when an operator has already installed the extension cluster
or database-wide; this module detects that case and proceeds without
attempting ``CREATE EXTENSION`` at all.
"""

from __future__ import annotations

from typing import Any


class VectorExtensionUnavailable(RuntimeError):
    """Raised when the ``vector`` extension is absent and this role cannot create it."""


def provision_vector_extension(conn: Any) -> None:
    """Ensure the PostgreSQL ``vector`` extension is installed, without requiring
    ``CREATE EXTENSION`` privilege when it is already present.

    Idempotent: safe to call on every :class:`~backend.persistence.postgres_adapter.PostgresStore`
    construction, before migrations run.

    Args:
        conn: Open psycopg connection.

    Raises:
        VectorExtensionUnavailable: The extension is absent and this
            connection's role cannot create it. The message names the
            operator action required (an operator with sufficient privilege
            must run ``CREATE EXTENSION vector;`` once, out of band).
    """
    already_installed = (
        conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
        is not None
    )
    if not already_installed:
        try:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as exc:  # noqa: BLE001 - surfaced as an actionable operator message
            raise VectorExtensionUnavailable(
                "PostgreSQL 'vector' extension (pgvector) is not installed and this "
                "database role cannot create it. Ask a database operator with "
                "sufficient privilege to run: CREATE EXTENSION vector;"
            ) from exc
    conn.commit()


__all__ = ["VectorExtensionUnavailable", "provision_vector_extension"]
