"""Shared SQLite/PostgreSQL persistence contract test suite (E56).

Every module in this package is written once per behavior and executed
against both backends through the ``backend``/``sql_store`` fixtures in
``conftest.py`` -- no ``if is_postgres`` branching belongs in a case body.
See ``docs/v2_platform/phases/e56_sqlite_postgres_contract_tests.md``.

Distinct from ``backend/tests/contract/``, the pre-existing E12-S2
extension-point contract tier (agents, providers, skills, ...) -- that
package proves plugin *extension points* keep a stable Protocol/manifest
shape; this one proves the *persistence layer* behaves identically on
SQLite and PostgreSQL.
"""
