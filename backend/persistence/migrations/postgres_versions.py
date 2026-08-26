"""Ordered migration list for :class:`backend.persistence.postgres_adapter.PostgresStore`.

Kept separate from ``versions.py`` (SQLite-only) both because the DDL dialect
differs and to keep each module under the repository's file-size guideline.
Each entry is a :class:`~backend.persistence.migrations.runner.Migration` (or
a bare ``(conn) -> None`` callable, wrapped with a no-op down) applying one
incremental DDL step against a psycopg connection — add new migrations by
appending to :data:`POSTGRES_STORE_MIGRATIONS`; never edit or reorder
existing entries.
"""

from __future__ import annotations

from typing import Any

from backend.persistence.migrations.runner import Migration, MigrationEntry
from backend.persistence.migrations.versions import TENANT_SCOPED_STORE_TABLES


def _pg_m1_create_core_tables(conn: Any) -> None:
    """Create :class:`PostgresStore`'s core tables and indexes.

    Reproduces the DDL that previously lived inline in
    ``PostgresStore._run_migrations`` (ad hoc ``CREATE TABLE IF NOT EXISTS``),
    now expressed as migration step 1 of the versioned runner so PostgreSQL
    and SQLite share the same migration machinery.

    Args:
        conn: Open psycopg connection.
    """
    statements = (
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            plan_json JSONB NOT NULL,
            artifacts_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            status TEXT NOT NULL,
            run_type TEXT NOT NULL DEFAULT 'existing_repo_change',
            current_state TEXT NOT NULL DEFAULT 'starting',
            trigger_message TEXT NOT NULL,
            results_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS run_steps (
            id BIGSERIAL PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step_key TEXT NOT NULL,
            agent TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS messages (
            id BIGSERIAL PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            run_id TEXT REFERENCES runs(id),
            sequence INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS plugins (
            id TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            state TEXT NOT NULL,
            manifest_path TEXT NOT NULL,
            manifest_json JSONB NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS plugin_events (
            id BIGSERIAL PRIMARY KEY,
            event_name TEXT NOT NULL,
            plugin_id TEXT NOT NULL,
            payload_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS eval_results (
            id BIGSERIAL PRIMARY KEY,
            eval_id TEXT NOT NULL,
            eval_version TEXT NOT NULL,
            run_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            gate_passed BOOLEAN NOT NULL DEFAULT TRUE,
            document_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(eval_id, eval_version, run_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS score_snapshots (
            id BIGSERIAL PRIMARY KEY,
            snapshot_id TEXT NOT NULL UNIQUE,
            sample_count INTEGER NOT NULL DEFAULT 0,
            document_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS score_snapshot_promotions (
            id BIGSERIAL PRIMARY KEY,
            policy_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            baseline_snapshot_id TEXT NOT NULL DEFAULT '',
            promoted BOOLEAN NOT NULL,
            reason TEXT NOT NULL,
            decided_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pg_runs_session_id ON runs(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_pg_run_steps_run_id ON run_steps(run_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_pg_messages_session_id ON messages(session_id, sequence)",
        "CREATE INDEX IF NOT EXISTS idx_pg_plugin_events_plugin_id ON plugin_events(plugin_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_pg_eval_results_eval_id ON eval_results(eval_id, eval_version, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pg_score_snapshots_created ON score_snapshots(id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pg_score_snapshot_promotions_policy_id "
        "ON score_snapshot_promotions(policy_id, id DESC)",
    )
    for statement in statements:
        conn.execute(statement)


def _pg_m2_add_tenant_id_and_rls(conn: Any) -> None:
    """Add ``tenant_id`` plus Row-Level Security to the core store tables.

    Scoped E8-S1 slice (ADR-010): applies a
    ``tenant_id TEXT NOT NULL DEFAULT 'default'`` column and an RLS policy
    scoping every row to ``current_setting('app.tenant_id', true)`` — set
    per-transaction via :func:`backend.persistence.tenancy.set_postgres_tenant`
    — on each table in
    :data:`~backend.persistence.migrations.versions.TENANT_SCOPED_STORE_TABLES`.
    Existing rows are backfilled to the ``'default'`` tenant so current
    single-tenant callers keep working unchanged. ``FORCE ROW LEVEL
    SECURITY`` is required alongside ``ENABLE`` because the application
    connects as the tables' owner, and Postgres exempts owners from RLS by
    default.

    Args:
        conn: Open psycopg connection.
    """
    for table in TENANT_SCOPED_STORE_TABLES:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'"
        )
        conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        conn.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        conn.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true))"
        )


def _pg_m2_down_tenant_id_and_rls(conn: Any) -> None:
    """Revert :func:`_pg_m2_add_tenant_id_and_rls` — drop RLS policies and the ``tenant_id`` column.

    Args:
        conn: Open psycopg connection.
    """
    for table in TENANT_SCOPED_STORE_TABLES:
        conn.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        conn.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        conn.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        conn.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id")


def _pg_m3_create_code_chunks_table(conn: Any) -> None:
    """Create the ``code_chunks`` table, its indexes, and Row-Level Security (E7-S1-T4).

    Persists syntax-aware chunk metadata — file path, symbol, line span, and
    content hash — produced by :mod:`backend.repository.chunking`. Unlike the
    core tables (retrofitted by migration 2), this new table is tenant-scoped
    and RLS-enabled from creation.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS code_chunks (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            file_path TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT '',
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            indexed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tenant_id, file_path, symbol, start_line)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_code_chunks_file_path ON code_chunks(tenant_id, file_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_code_chunks_hash ON code_chunks(content_hash)")
    conn.execute("ALTER TABLE code_chunks ENABLE ROW LEVEL SECURITY")
    conn.execute("ALTER TABLE code_chunks FORCE ROW LEVEL SECURITY")
    conn.execute("DROP POLICY IF EXISTS code_chunks_tenant_isolation ON code_chunks")
    conn.execute(
        "CREATE POLICY code_chunks_tenant_isolation ON code_chunks "
        "USING (tenant_id = current_setting('app.tenant_id', true))"
    )


def _pg_m3_down_drop_code_chunks_table(conn: Any) -> None:
    """Revert :func:`_pg_m3_create_code_chunks_table` by dropping the table (and its policy/indexes with it).

    Args:
        conn: Open psycopg connection.
    """
    conn.execute("DROP TABLE IF EXISTS code_chunks")


#: Vector dimension baked into the ``code_embeddings.embedding`` column.
#: pgvector requires a fixed dimension per column. Must match
#: ``backend.repository.embeddings.provider.DEFAULT_EMBEDDING_DIMENSION`` —
#: kept as a literal here (rather than imported) so this persistence-layer
#: module has no dependency on the repository layer; see ADR-011.
_CODE_EMBEDDING_DIMENSION = 128


def _pg_m4_create_code_embeddings_table(conn: Any) -> None:
    """Create the ``code_embeddings`` table, HNSW index, and RLS (E7-S2).

    Requires PostgreSQL's ``vector`` extension (pgvector) to already be
    installed — since E48-S2/ADR-024, provisioning it is a separate step
    (:func:`~backend.persistence.postgres_adapter.vector_provisioning.provision_vector_extension`)
    run before the migration runner, so schema migration itself no longer
    needs ``CREATE EXTENSION`` privilege. Uses an HNSW index over cosine
    distance (``vector_cosine_ops``) rather than IVFFlat — see ADR-011 for
    the recall/latency trade-off this records.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS code_embeddings (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            chunk_id BIGINT NOT NULL REFERENCES code_chunks(id) ON DELETE CASCADE,
            content_hash TEXT NOT NULL,
            embedding vector({_CODE_EMBEDDING_DIMENSION}) NOT NULL,
            model TEXT NOT NULL DEFAULT 'stub',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tenant_id, chunk_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pg_code_embeddings_hnsw "
        "ON code_embeddings USING hnsw (embedding vector_cosine_ops)"
    )
    conn.execute("ALTER TABLE code_embeddings ENABLE ROW LEVEL SECURITY")
    conn.execute("ALTER TABLE code_embeddings FORCE ROW LEVEL SECURITY")
    conn.execute("DROP POLICY IF EXISTS code_embeddings_tenant_isolation ON code_embeddings")
    conn.execute(
        "CREATE POLICY code_embeddings_tenant_isolation ON code_embeddings "
        "USING (tenant_id = current_setting('app.tenant_id', true))"
    )


def _pg_m4_down_drop_code_embeddings_table(conn: Any) -> None:
    """Revert :func:`_pg_m4_create_code_embeddings_table` by dropping the table.

    The ``vector`` extension itself is intentionally left installed — it is
    cluster/database-wide and other tables may depend on it.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute("DROP TABLE IF EXISTS code_embeddings")


def _pg_m5_add_content_column_to_code_chunks(conn: Any) -> None:
    """Add a ``content`` column plus a full-text search index to ``code_chunks`` (E7-S3-T1).

    Hybrid retrieval needs the chunk's actual source text to search/return —
    ``code_chunks`` previously stored only span/hash metadata. A GIN index
    over ``to_tsvector('english', content)`` backs
    ``backend/repository/retrieval/lexical.py``'s ``ts_rank`` search.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute("ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT ''")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pg_code_chunks_fts ON code_chunks "
        "USING GIN (to_tsvector('english', content))"
    )


def _pg_m5_down_remove_content_column_from_code_chunks(conn: Any) -> None:
    """Revert :func:`_pg_m5_add_content_column_to_code_chunks`.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute("DROP INDEX IF EXISTS idx_pg_code_chunks_fts")
    conn.execute("ALTER TABLE code_chunks DROP COLUMN IF EXISTS content")


#: Plan store tables retrofitted with a ``tenant_id`` column (E8-S1-T3, ADR-010).
#: Unlike :data:`~backend.persistence.migrations.versions.TENANT_SCOPED_STORE_TABLES`,
#: these tables belong to
#: :class:`~backend.persistence.postgres_adapter.PostgresPlanStore`, not
#: :class:`~backend.persistence.postgres_adapter.PostgresStore`.
PLAN_STORE_TENANT_SCOPED_TABLES = ("plan_documents", "plan_approvals")


def add_tenant_id_and_rls_to_plan_tables(conn: Any) -> None:
    """Add ``tenant_id`` plus Row-Level Security to the plan store's tables.

    Mirrors :func:`_pg_m2_add_tenant_id_and_rls`, applied to
    :data:`PLAN_STORE_TENANT_SCOPED_TABLES` instead of the core store
    tables. Deliberately *not* underscore-prefixed (unlike its sibling
    ``_pg_mN_*`` steps): it is invoked from two independent call sites —
    once as a step in :data:`POSTGRES_STORE_MIGRATIONS` (so a fresh
    :class:`~backend.persistence.postgres_adapter.PostgresStore` brings
    these tables up to date too), and once directly from
    :meth:`~backend.persistence.postgres_adapter.PostgresPlanStore._run_migrations`
    (so a fresh :class:`~backend.persistence.postgres_adapter.PostgresPlanStore`
    is correct even if a :class:`PostgresStore` is never constructed against
    the same database). Because either store may bootstrap first against a
    fresh database, this step (unlike migration 2) also guards its target
    tables with ``CREATE TABLE IF NOT EXISTS`` — an ``ALTER TABLE`` against a
    table that does not yet exist would otherwise fail outright.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_documents (
            session_id TEXT PRIMARY KEY,
            steps_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            status TEXT NOT NULL DEFAULT 'draft',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_approvals (
            id BIGSERIAL PRIMARY KEY,
            session_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            actor TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    for table in PLAN_STORE_TENANT_SCOPED_TABLES:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'"
        )
        conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        conn.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        conn.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true))"
        )


def revert_tenant_id_and_rls_from_plan_tables(conn: Any) -> None:
    """Revert :func:`add_tenant_id_and_rls_to_plan_tables`.

    Drops the RLS policy, enforcement, and ``tenant_id`` column for each of
    :data:`PLAN_STORE_TENANT_SCOPED_TABLES`. Mirrors
    :func:`_pg_m2_down_tenant_id_and_rls`; the tables themselves are left in
    place (only their retrofitted tenancy is undone).

    Args:
        conn: Open psycopg connection.
    """
    for table in PLAN_STORE_TENANT_SCOPED_TABLES:
        conn.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        conn.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        conn.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        conn.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id")


def _pg_m6_unique_message_sequence(conn: Any) -> None:
    """Add a unique index on ``messages (tenant_id, session_id, sequence)`` (E44-S4).

    Postgres counterpart of
    :func:`backend.persistence.migrations.versions._m10_unique_message_sequence`:
    sequence numbers are allocated as ``MAX(sequence) + 1`` inside the append
    transaction, and this index makes two concurrent appends that read the
    same maximum fail closed instead of writing duplicates.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_tenant_session_sequence "
        "ON messages (tenant_id, session_id, sequence)"
    )


def _pg_m6_down_unique_message_sequence(conn: Any) -> None:
    """Revert :func:`_pg_m6_unique_message_sequence` by dropping the index.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute("DROP INDEX IF EXISTS idx_messages_tenant_session_sequence")


def _pg_m7_run_step_position(conn: Any) -> None:
    """Give ``run_steps`` a stable ``position`` key and a unique index on it (E44-S5).

    Postgres counterpart of
    :func:`backend.persistence.migrations.versions._m11_run_step_position`:
    ``position`` (the step's index in the run's ordered step list) is the
    upsert key a checkpoint targets, so persisting the Nth step writes one row
    instead of re-inserting all N. Existing rows are backfilled from their
    insertion order.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute("ALTER TABLE run_steps ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        """
        UPDATE run_steps SET position = ranked.rank - 1
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY id) AS rank
            FROM run_steps
        ) AS ranked
        WHERE run_steps.id = ranked.id AND run_steps.position = 0
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_run_steps_run_position "
        "ON run_steps (run_id, position)"
    )


def _pg_m7_down_run_step_position(conn: Any) -> None:
    """Revert :func:`_pg_m7_run_step_position`, dropping the index and column.

    Args:
        conn: Open psycopg connection.
    """
    conn.execute("DROP INDEX IF EXISTS idx_run_steps_run_position")
    conn.execute("ALTER TABLE run_steps DROP COLUMN IF EXISTS position")


def _pg_m8_create_quota_and_secret_tables(conn: Any) -> None:
    """Create the quota, lease, reservation, and secret tables (E50-S1).

    These five quota/lease tables and the ``secrets`` table were previously
    created imperatively by :class:`backend.quotas.store.QuotaStore` and
    :class:`backend.secret_store.store.SecretStore` (SQLite-only, per
    E49-S2/ADR-025), with no PostgreSQL counterpart and no
    ``schema_version`` tracking. This migration mirrors their SQLite shape
    with PostgreSQL types (``JSONB``, ``TIMESTAMPTZ``, ``BIGINT``) and
    tenant-first keys/indexes. Row-Level Security is applied separately by
    :func:`_pg_m11_apply_tenant_rls_to_new_tables` (E50-S4) — these tables
    are legitimately unread on PostgreSQL until their store port lands
    (E51, E52).

    Args:
        conn: Open psycopg connection.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_quota_policies (
            tenant_id TEXT PRIMARY KEY,
            policy_json JSONB NOT NULL,
            version BIGINT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_usage_windows (
            tenant_id TEXT NOT NULL,
            resource TEXT NOT NULL,
            window_key TEXT NOT NULL,
            used BIGINT NOT NULL DEFAULT 0,
            warned INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (tenant_id, resource, window_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_leases (
            run_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            released_at TIMESTAMPTZ
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pg_run_leases_tenant "
        "ON run_leases(tenant_id, released_at, expires_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_reservations (
            reservation_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            bytes BIGINT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pg_storage_reservations_tenant "
        "ON storage_reservations(tenant_id, status)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS request_rate_buckets (
            tenant_id TEXT NOT NULL DEFAULT 'default',
            credential_id TEXT NOT NULL,
            window_start BIGINT NOT NULL,
            count BIGINT NOT NULL DEFAULT 0,
            PRIMARY KEY (tenant_id, credential_id, window_start)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pg_request_rate_buckets_tenant "
        "ON request_rate_buckets(tenant_id, credential_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS secrets (
            tenant_id TEXT NOT NULL,
            project TEXT NOT NULL,
            name TEXT NOT NULL,
            version BIGINT NOT NULL,
            ciphertext TEXT NOT NULL,
            status TEXT NOT NULL,
            backend_kind TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            rotated_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            PRIMARY KEY (tenant_id, project, name, version)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pg_secrets_latest "
        "ON secrets(tenant_id, project, name, version DESC)"
    )


def _pg_m8_down_drop_quota_and_secret_tables(conn: Any) -> None:
    """Revert :func:`_pg_m8_create_quota_and_secret_tables` by dropping its six tables.

    Args:
        conn: Open psycopg connection.
    """
    for table in (
        "tenant_quota_policies",
        "tenant_usage_windows",
        "run_leases",
        "storage_reservations",
        "request_rate_buckets",
        "secrets",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {table}")


POSTGRES_STORE_MIGRATIONS: list[MigrationEntry] = [
    _pg_m1_create_core_tables,
    Migration(
        up=_pg_m2_add_tenant_id_and_rls,
        down=_pg_m2_down_tenant_id_and_rls,
        name="add_tenant_id_and_rls",
    ),
    Migration(
        up=_pg_m3_create_code_chunks_table,
        down=_pg_m3_down_drop_code_chunks_table,
        name="create_code_chunks_table",
    ),
    Migration(
        up=_pg_m4_create_code_embeddings_table,
        down=_pg_m4_down_drop_code_embeddings_table,
        name="create_code_embeddings_table",
    ),
    Migration(
        up=_pg_m5_add_content_column_to_code_chunks,
        down=_pg_m5_down_remove_content_column_from_code_chunks,
        name="add_content_column_to_code_chunks",
    ),
    Migration(
        up=add_tenant_id_and_rls_to_plan_tables,
        down=revert_tenant_id_and_rls_from_plan_tables,
        name="add_tenant_id_and_rls_to_plan_tables",
    ),
    Migration(
        up=_pg_m6_unique_message_sequence,
        down=_pg_m6_down_unique_message_sequence,
        name="unique_message_sequence",
    ),
    Migration(
        up=_pg_m7_run_step_position,
        down=_pg_m7_down_run_step_position,
        name="run_step_position",
    ),
    Migration(
        up=_pg_m8_create_quota_and_secret_tables,
        down=_pg_m8_down_drop_quota_and_secret_tables,
        name="create_quota_and_secret_tables",
    ),
]


__all__ = ["POSTGRES_STORE_MIGRATIONS"]
