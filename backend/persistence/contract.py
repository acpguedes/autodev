"""Shared SQL dialect contract for domain stores (E49-S1, ADR-025).

Eight stores (flows, events, artifacts, auth, plugins, repository indexing)
each hand-roll the same small pattern: detect SQLite vs PostgreSQL from a
``database_url``, pick a ``?``/``%s`` placeholder, and — for a JSON column —
append (or not) a ``::jsonb`` cast. This module is the single implementation
of that pattern; see ``backend/persistence/codecs.py``'s own docstring for
why it stays separate ("this module intentionally contains no SQL and no
backend branching") — this module is exactly the inverse: it is *only*
dialect branching, no row/document shaping.

No ORM and no query builder (ADR-025): SQL text stays explicit and
hand-written in each store; this module only supplies the small, named
primitives that text needs to vary by dialect.
"""

from __future__ import annotations

from typing import Any


def is_postgres(database_url: str) -> bool:
    """Return whether *database_url* addresses a PostgreSQL database.

    The one implementation of a check ~8 stores previously duplicated
    (with two slightly different ``.startswith`` spellings).

    Args:
        database_url: A store's ``database_url`` (e.g. ``store.database_url``).

    Returns:
        ``True`` for a ``postgresql://``/``postgres://`` URL, else ``False``.
    """
    url = str(database_url or "")
    return url.startswith(("postgresql://", "postgres://"))


def placeholder(is_pg: bool) -> str:
    """Return this dialect's positional-parameter placeholder: ``%s`` or ``?``."""
    return "%s" if is_pg else "?"


def jsonb_cast(is_pg: bool) -> str:
    """Return the cast suffix a JSON-column placeholder needs: ``::jsonb`` or none.

    PostgreSQL's ``jsonb`` columns require a cast when the value is bound as
    a plain string parameter; SQLite's ``TEXT`` columns need nothing.
    """
    return "::jsonb" if is_pg else ""


def sql(template: str, is_pg: bool) -> str:
    """Render a dialect-parameterized SQL template.

    *template* may reference ``{p}`` (the placeholder) and ``{jsonb}`` (the
    JSON-column cast suffix, for templates with a JSON parameter); either or
    both may be omitted. Generalizes the ``_sql()``/``{p}``-template method
    duplicated across ``FlowRunStore``, ``EventStore``, ``ArtifactPointerStore``,
    and ``AuthStore``, extended with ``{jsonb}`` so stores that previously
    wrote two full dual-branch statements (``registry.py``, ``PluginStore``,
    ``VersionedExtensionRegistryCore``) can write one.

    Args:
        template: SQL text with ``{p}``/``{jsonb}`` format tokens.
        is_pg: Whether the target connection is PostgreSQL.

    Returns:
        *template* with its dialect tokens substituted.
    """
    return template.format(p=placeholder(is_pg), jsonb=jsonb_cast(is_pg))


def json_column_type(is_pg: bool) -> str:
    """Return the DDL column type for a JSON-valued column: ``JSONB`` or ``TEXT``."""
    return "JSONB" if is_pg else "TEXT"


def timestamp_column_type(is_pg: bool) -> str:
    """Return the DDL column type for a timestamp column: ``TIMESTAMPTZ`` or ``TEXT``."""
    return "TIMESTAMPTZ" if is_pg else "TEXT"


def begin_write(conn: Any, is_pg: bool) -> None:
    """Start a write transaction with the serialization guarantee both dialects need.

    SQLite: issues ``BEGIN IMMEDIATE`` — a real file lock, safe across
    threads and processes on one machine, taken before the read-then-write
    sequence that would otherwise risk a busy/upgrade error. PostgreSQL: a
    no-op here — the connection is already in an explicit transaction (not
    autocommit) once a statement runs, and row-level serialization is
    provided by :func:`for_update_clause` on the specific rows being locked,
    not by an upfront database-wide write lock. Generalizes the
    ``_begin_write()`` method duplicated in ``FlowRunStore``, ``EventStore``,
    and ``AuthStore``.

    Args:
        conn: Open connection (SQLite or PostgreSQL).
        is_pg: Whether *conn* is a PostgreSQL connection.
    """
    if not is_pg:
        conn.execute("BEGIN IMMEDIATE")


def for_update_clause(is_pg: bool) -> str:
    """Return the row-lock clause to append to a ``SELECT`` inside a critical section.

    PostgreSQL: ``" FOR UPDATE"``, taking an explicit row lock for the
    duration of the transaction. SQLite: ``""`` — :func:`begin_write`'s
    ``BEGIN IMMEDIATE`` already holds an exclusive write lock over the whole
    database for the transaction, so no additional row-level syntax is
    needed or valid.

    This is the primitive ``backend/quotas/store.py``'s docstring described
    (inaccurately, for today's SQLite-only implementation) as already
    existing; it becomes real when that store is ported to PostgreSQL (E51).

    Args:
        is_pg: Whether the target connection is PostgreSQL.
    """
    return " FOR UPDATE" if is_pg else ""


class PersistenceIntegrityError(Exception):
    """Backend-agnostic integrity-constraint violation (unique/foreign-key/check).

    Callers that need to react to a constraint violation (e.g. "this row
    already exists") should catch this instead of a backend-specific
    exception type, via :func:`translate_integrity_error`.
    """


def translate_integrity_error(exc: Exception) -> PersistenceIntegrityError:
    """Wrap a caught backend integrity error as :class:`PersistenceIntegrityError`.

    Call from within an ``except`` clause already scoped to a
    backend-specific integrity error — ``sqlite3.IntegrityError``, or
    ``psycopg.errors.IntegrityError``/``UniqueViolation``/etc. (this module
    never imports ``psycopg``, an optional dependency, so it does not
    enumerate those types itself)::

        try:
            ...
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc) from exc

    Args:
        exc: The backend-specific exception caught by the caller.

    Returns:
        A :class:`PersistenceIntegrityError` wrapping *exc*'s message, with
        *exc* set as its ``__cause__`` — so even ``raise
        translate_integrity_error(exc)`` alone, without an explicit ``from
        exc``, preserves the original exception in the traceback.
    """
    result = PersistenceIntegrityError(str(exc))
    result.__cause__ = exc
    return result


def get_connection(store: Any = None) -> Any:
    """Open a connection from the configured (or given) store.

    Formalizes the app-wide ``self._store = store or get_store()`` idiom
    (used identically across ~19 call sites — flows, events, artifacts,
    auth, plugins, orchestrator, ...) into one documented helper for the
    category-3 stores (quotas, secrets, policy, environments, plan step
    state) to target when they are ported onto this contract (E51-E55).
    None of the 8 stores E49 itself migrates need this — they already
    acquire their store via ``get_store()`` at construction time, not per
    connection.

    Args:
        store: An existing store exposing ``connect()``, or ``None`` to use
            the process-wide configured store.

    Returns:
        A new connection from the resolved store.
    """
    from backend.persistence.database import get_store

    return (store or get_store()).connect()


__all__ = [
    "PersistenceIntegrityError",
    "begin_write",
    "for_update_clause",
    "get_connection",
    "is_postgres",
    "json_column_type",
    "jsonb_cast",
    "placeholder",
    "sql",
    "timestamp_column_type",
    "translate_integrity_error",
]
