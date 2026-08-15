"""Unit tests for the Trivy vulnerability/license exception policy."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backend.security.exceptions import (
    SecurityException,
    SecurityExceptionError,
    validate_trivy_exceptions,
)


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / ".trivyignore.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_empty_vulnerability_and_license_lists_are_valid(tmp_path: Path) -> None:
    """A fail-closed baseline with no exceptions validates to an empty tuple."""
    path = _write(tmp_path, "vulnerabilities: []\nlicenses: []\n")

    assert validate_trivy_exceptions(path, today=date(2026, 8, 15)) == ()


def test_valid_future_exception_is_accepted(tmp_path: Path) -> None:
    """A well-formed exception that has not yet expired is returned."""
    path = _write(
        tmp_path,
        "vulnerabilities:\n"
        "  - id: CVE-2099-0001\n"
        "    statement: approved-by=security-team; reason=temporary mitigation\n"
        "    expires_at: 2099-01-01\n"
        "licenses: []\n",
    )

    exceptions = validate_trivy_exceptions(path, today=date(2026, 8, 15))

    assert exceptions == (
        SecurityException(
            finding_id="CVE-2099-0001",
            category="vulnerabilities",
            statement="approved-by=security-team; reason=temporary mitigation",
            expires_at=date(2099, 1, 1),
        ),
    )


def test_missing_statement_is_rejected(tmp_path: Path) -> None:
    """An entry without a statement fails validation."""
    path = _write(
        tmp_path,
        "vulnerabilities:\n"
        "  - id: CVE-2099-0002\n"
        "    expires_at: 2099-01-01\n"
        "licenses: []\n",
    )

    with pytest.raises(SecurityExceptionError, match="statement"):
        validate_trivy_exceptions(path, today=date(2026, 8, 15))


def test_statement_without_approved_by_and_reason_is_rejected(tmp_path: Path) -> None:
    """A statement missing the approved-by=...; reason=... shape is rejected."""
    path = _write(
        tmp_path,
        "vulnerabilities:\n"
        "  - id: CVE-2099-0003\n"
        "    statement: this is not the right shape\n"
        "    expires_at: 2099-01-01\n"
        "licenses: []\n",
    )

    with pytest.raises(SecurityExceptionError, match="approved-by"):
        validate_trivy_exceptions(path, today=date(2026, 8, 15))


def test_malformed_iso_date_is_rejected(tmp_path: Path) -> None:
    """An unparseable expires_at value fails validation."""
    path = _write(
        tmp_path,
        "vulnerabilities:\n"
        "  - id: CVE-2099-0004\n"
        "    statement: approved-by=security-team; reason=temporary mitigation\n"
        "    expires_at: not-a-date\n"
        "licenses: []\n",
    )

    with pytest.raises(SecurityExceptionError, match="ISO"):
        validate_trivy_exceptions(path, today=date(2026, 8, 15))


def test_expired_security_exception_is_rejected(tmp_path: Path) -> None:
    """An exception whose expires_at date has passed is rejected, not silently kept."""
    ignore = tmp_path / ".trivyignore.yaml"
    ignore.write_text(
        "vulnerabilities:\n"
        "  - id: CVE-2099-0001\n"
        "    statement: approved-by=security-team; reason=temporary mitigation\n"
        "    expires_at: 2026-08-14\n"
        "licenses: []\n",
        encoding="utf-8",
    )

    with pytest.raises(SecurityExceptionError, match="expired"):
        validate_trivy_exceptions(
            ignore,
            today=date(2026, 8, 15),
        )


def test_duplicate_category_and_id_pair_is_rejected(tmp_path: Path) -> None:
    """Two entries for the same (category, id) pair are rejected as ambiguous."""
    path = _write(
        tmp_path,
        "vulnerabilities:\n"
        "  - id: CVE-2099-0005\n"
        "    statement: approved-by=security-team; reason=first\n"
        "    expires_at: 2099-01-01\n"
        "  - id: CVE-2099-0005\n"
        "    statement: approved-by=security-team; reason=second\n"
        "    expires_at: 2099-01-01\n"
        "licenses: []\n",
    )

    with pytest.raises(SecurityExceptionError, match="duplicate"):
        validate_trivy_exceptions(path, today=date(2026, 8, 15))


def test_expires_at_exactly_today_is_still_valid(tmp_path: Path) -> None:
    """An exception expiring today is inclusive: still valid on its expiry date."""
    path = _write(
        tmp_path,
        "vulnerabilities:\n"
        "  - id: CVE-2099-0006\n"
        "    statement: approved-by=security-team; reason=last day\n"
        "    expires_at: 2026-08-15\n"
        "licenses: []\n",
    )

    exceptions = validate_trivy_exceptions(path, today=date(2026, 8, 15))

    assert len(exceptions) == 1
