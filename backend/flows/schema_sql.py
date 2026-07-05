"""DDL for the flow run/step/event tables (SQLite and PostgreSQL)."""

from __future__ import annotations


def flow_state_statements(is_postgres: bool) -> tuple[str, ...]:
    """Build the CREATE TABLE/INDEX statements for the flow state schema.

    Args:
        is_postgres: Whether to emit PostgreSQL types (JSONB/TIMESTAMPTZ).

    Returns:
        The ordered DDL statements.
    """
    if is_postgres:
        json_type, time_type = "JSONB", "TIMESTAMPTZ"
    else:
        json_type, time_type = "TEXT", "TEXT"
    return (
        f"""
        CREATE TABLE IF NOT EXISTS flow_runs (
            run_id TEXT PRIMARY KEY,
            flow_id TEXT NOT NULL,
            flow_version TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            status TEXT NOT NULL,
            stop_reason TEXT NOT NULL DEFAULT '',
            trigger_json {json_type},
            input_json {json_type},
            state_json {json_type},
            output_json {json_type},
            parent_run_id TEXT,
            created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS flow_steps (
            step_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            node_type TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            input_json {json_type},
            output_json {json_type},
            error TEXT NOT NULL DEFAULT '',
            started_at {time_type} NOT NULL,
            completed_at TEXT NOT NULL DEFAULT '',
            sequence INTEGER NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS flow_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            name TEXT NOT NULL,
            payload_json {json_type},
            created_at {time_type} NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_flow_runs_flow ON flow_runs(flow_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_flow_steps_run ON flow_steps(run_id, sequence)",
        "CREATE INDEX IF NOT EXISTS idx_flow_events_run ON flow_events(run_id, sequence)",
    )
    
