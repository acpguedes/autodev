"""Boundary guard: no domain module opens a database connection directly (E49-S4, ADR-025).

Asserts that ``sqlite3.connect(``/``psycopg.connect(`` never appears outside
``backend/persistence/`` except at an explicit, story-annotated allowlist
entry. Detects the attribute-call form (``sqlite3.connect(...)``,
``psycopg.connect(...)``) via AST, which is the only form used anywhere in
this codebase today — it deliberately does not chase aliased imports
(``from sqlite3 import connect as _connect``), since none exist.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_ROOT = _REPO_ROOT / "backend"

_CONNECT_TARGETS = {("sqlite3", "connect"), ("psycopg", "connect")}

#: (repo-relative path, line number) -> the story that removes this entry,
#: or "never" for a permanent, legitimate exception. Every entry here is a
#: real direct-connect call site as of this epic; the allowlist must shrink
#: as E51-E55 land, never grow silently (ADR-025).
#:
#: ``backend/persistence/backup.py``'s four native-SQLite-backup-API call
#: sites (snapshot/restore) need no entry here at all: the scan below
#: excludes all of ``backend/persistence/`` by design (ADR-025: "sqlite3 and
#: psycopg imports belong to backend/persistence/ only" - so persistence/
#: modules using them directly is not a boundary violation to begin with).
_ALLOWLIST: dict[tuple[str, int], str] = {
    ("backend/ops/doctor.py", 119): (
        "never - preflight connectivity check deliberately below the "
        "persistence layer (must not construct a Store or run migrations "
        "as a side effect of a health check)"
    ),
    ("backend/ops/doctor.py", 222): (
        "never - pgvector readiness checks (E48), same reason as :119 - "
        "deliberately below the persistence layer"
    ),
    ("backend/quotas/migrations.py", 153): "never - read-only tenancy verifier CLI check (PostgreSQL branch)",
    ("backend/quotas/migrations.py", 159): "never - read-only tenancy verifier CLI check (SQLite branch)",
    ("backend/execution/policy.py", 227): "E53 - PolicyStore on PostgreSQL",
    ("backend/plans/step_state.py", 200): "E55 - Plan Step State on PostgreSQL",
}


def _find_direct_connect_calls(path: Path) -> list[int]:
    """Return the line numbers of ``sqlite3.connect(``/``psycopg.connect(`` calls in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
            continue
        if (func.value.id, func.attr) in _CONNECT_TARGETS:
            hits.append(node.lineno)
    return hits


def _scan_backend() -> dict[str, list[int]]:
    """Scan ``backend/`` (excluding ``backend/persistence/`` and ``backend/tests/``)
    for direct ``sqlite3.connect(``/``psycopg.connect(`` call sites."""
    findings: dict[str, list[int]] = {}
    for path in sorted(_BACKEND_ROOT.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel.startswith("backend/persistence/") or rel.startswith("backend/tests/"):
            continue
        lines = _find_direct_connect_calls(path)
        if lines:
            findings[rel] = lines
    return findings


def test_no_domain_module_opens_a_database_connection_directly() -> None:
    """Every direct-connect call site outside backend/persistence/ is allowlisted."""
    findings = _scan_backend()
    violations = [
        f"{rel_path}:{line}"
        for rel_path, lines in findings.items()
        for line in lines
        if (rel_path, line) not in _ALLOWLIST
    ]
    assert not violations, (
        "Unallowlisted direct database connection outside backend/persistence/: "
        + ", ".join(violations)
        + ". Route connection acquisition through backend/persistence/ "
        "(e.g. backend.persistence.contract.get_connection), or add an "
        "explicit, story-annotated allowlist entry here (ADR-025)."
    )


def test_boundary_guard_allowlist_has_no_stale_entries() -> None:
    """Every allowlisted (file, line) still names a real direct-connect call site.

    Enforces "the allowlist shrinks and never grows silently" (ADR-025): once
    a store is ported (e.g. E51 removes quotas/store.py:70), its allowlist
    entry must be deleted too, not left dangling.
    """
    findings = _scan_backend()
    stale = [
        f"{rel_path}:{line} ({reason})"
        for (rel_path, line), reason in _ALLOWLIST.items()
        if line not in findings.get(rel_path, [])
    ]
    assert not stale, "Stale boundary-guard allowlist entries, shrink the allowlist: " + ", ".join(
        stale
    )


def test_detector_flags_direct_sqlite3_connect(tmp_path: Path) -> None:
    """The AST detector recognizes ``sqlite3.connect(...)``."""
    synthetic = tmp_path / "synthetic_module.py"
    synthetic.write_text("import sqlite3\n\ndef f():\n    return sqlite3.connect('x.db')\n")

    assert _find_direct_connect_calls(synthetic) == [4]


def test_detector_flags_direct_psycopg_connect(tmp_path: Path) -> None:
    """The AST detector recognizes ``psycopg.connect(...)``."""
    synthetic = tmp_path / "synthetic_module.py"
    synthetic.write_text(
        "import psycopg\n\ndef f():\n    return psycopg.connect('postgresql://x')\n"
    )

    assert _find_direct_connect_calls(synthetic) == [4]


def test_detector_does_not_flag_the_store_connect_idiom(tmp_path: Path) -> None:
    """The app-wide ``store.connect()``/``self._store.connect()`` idiom is not a false positive."""
    synthetic = tmp_path / "synthetic_module.py"
    synthetic.write_text(
        "def f(store):\n    with store.connect() as conn:\n        return conn\n"
    )

    assert _find_direct_connect_calls(synthetic) == []
