"""Shared multi-tenancy helpers (E8-S1 scoped slice — see ADR-010).

This module is intentionally small. It provides the primitives the new E7
tables (``code_chunks``, ``code_embeddings``) and the tenant_id-retrofitted
core tables (sessions/runs/messages/plugins/eval_results/score_snapshots)
need to scope reads/writes to a tenant. It does **not** rewrite every
repository method's call sites across the app to require a tenant argument —
that broader migration is out of scope for this slice (see ADR-010).
"""

from __future__ import annotations

from typing import Any

#: Tenant id used for all data created before/without explicit multi-tenancy,
#: and the default scope for single-tenant (local-first) deployments.
DEFAULT_TENANT_ID = "default"


def set_postgres_tenant(conn: Any, tenant_id: str = DEFAULT_TENANT_ID) -> None:
    """Scope the rest of the current transaction to *tenant_id* via Postgres RLS.

    Uses ``set_config('app.tenant_id', tenant_id, true)`` rather than a
    literal ``SET LOCAL app.tenant_id = ...`` statement, because PostgreSQL
    does not accept bound parameters inside ``SET``/``SET LOCAL`` — passing
    an untrusted ``tenant_id`` there would require unsafe string
    interpolation. ``set_config`` is the documented, parameter-safe way to
    set a session/transaction GUC; its third argument (``true``) makes the
    change transaction-local, equivalent to ``SET LOCAL``. Row-Level Security
    policies on tenant-scoped tables read this value back via
    ``current_setting('app.tenant_id', true)`` (see
    ``backend/persistence/migrations/versions.py``).

    Args:
        conn: Open psycopg connection (or connection-like object exposing
            ``execute``), with an open transaction.
        tenant_id: Tenant identifier to scope subsequent queries in this
            transaction to.

    Raises:
        ValueError: If ``tenant_id`` is empty.
    """
    if not tenant_id:
        raise ValueError("tenant_id must be a non-empty string")
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id, ))


def sqlite_tenant_clause(
    tenant_id: str = DEFAULT_TENANT_ID, *, param_style: str = "?"
) -> tuple[str, tuple[str]]:
    """Return a ``WHERE``-clause fragment and params scoping a SQLite query to *tenant_id*.

    SQLite has no Row-Level Security equivalent, so tenant isolation there is
    enforced by appending this fragment (and its params) to hand-written
    queries — e.g.::

        clause, params = sqlite_tenant_clause(tenant_id)
        conn.execute(f"SELECT * FROM code_chunks WHERE 1=1 {clause}", params)

    Args:
        tenant_id: Tenant identifier to scope the query to.
        param_style: Placeholder style to emit. ``"?"`` (SQLite's default,
            positional) unless the caller builds dialect-parameterized SQL
            through shared code and needs ``"%s"``.

    Returns:
        A ``(sql_fragment, params)`` pair; ``sql_fragment`` starts with
        ``AND`` so it composes directly after a ``WHERE 1=1`` or another
        ``AND``-ed predicate.

    Raises:
        ValueError: If ``tenant_id`` is empty.
    """
    if not tenant_id:
        raise ValueError("tenant_id must be a non-empty string")
    return f"AND tenant_id = {param_style}", (tenant_id, )


__all__ = ["DEFAULT_TENANT_ID", "set_postgres_tenant", "sqlite_tenant_clause"]
