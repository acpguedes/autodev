"""Typed, expiring approval policy for Trivy vulnerability/license exceptions.

A ``.trivyignore.yaml`` entry is only honored when it carries an auditable
approval statement and has not expired. This keeps exceptions a deliberate,
time-bounded decision rather than a silent, permanent suppression.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml

_STATEMENT_PATTERN = re.compile(
    r"^approved-by=(?P<approved_by>[^;]+); reason=(?P<reason>.+)$"
)

_CATEGORIES: tuple[str, ...] = ("vulnerabilities", "licenses")


@dataclass(frozen=True)
class SecurityException:
    """One approved, expiring Trivy finding exception.

    Attributes:
        finding_id: Trivy finding identifier (CVE id or license name).
        category: Whether this exempts a vulnerability or a license finding.
        statement: Human-readable approval statement, ``approved-by=...;
            reason=...``.
        expires_at: Date this exception stops applying (inclusive).
    """

    finding_id: str
    category: Literal["vulnerabilities", "licenses"]
    statement: str
    expires_at: date


class SecurityExceptionError(ValueError):
    """Raised when a Trivy exception is malformed or expired."""


def _require_str(value: Any, *, field: str, entry_index: int, category: str) -> str:
    """Require a non-empty string field on one exception entry.

    Args:
        value: Raw field value.
        field: Field name, used in the error message.
        entry_index: Zero-based index of the entry within its category list.
        category: Category the entry belongs to.

    Returns:
        The validated string.

    Raises:
        SecurityExceptionError: If the value is missing or not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise SecurityExceptionError(
            f"{category}[{entry_index}]: '{field}' is required and must be a "
            "non-empty string"
        )
    return value.strip()


def _parse_entry(
    raw: Any, *, category: Literal["vulnerabilities", "licenses"], entry_index: int
) -> SecurityException:
    """Parse and validate one raw exception entry.

    Args:
        raw: Raw mapping loaded from YAML.
        category: Category the entry belongs to.
        entry_index: Zero-based index within its category list.

    Returns:
        The validated exception.

    Raises:
        SecurityExceptionError: If the entry is malformed.
    """
    if not isinstance(raw, dict):
        raise SecurityExceptionError(
            f"{category}[{entry_index}]: entry must be a mapping"
        )
    finding_id = _require_str(raw.get("id"), field="id", entry_index=entry_index, category=category)
    statement = _require_str(
        raw.get("statement"), field="statement", entry_index=entry_index, category=category
    )
    match = _STATEMENT_PATTERN.match(statement)
    if match is None or not match.group("approved_by").strip() or not match.group("reason").strip():
        raise SecurityExceptionError(
            f"{category}[{entry_index}]: 'statement' must match "
            "'approved-by=<identity>; reason=<rationale>'"
        )
    raw_expires = raw.get("expires_at")
    if isinstance(raw_expires, date):
        expires_at = raw_expires
    elif isinstance(raw_expires, str):
        try:
            expires_at = date.fromisoformat(raw_expires.strip())
        except ValueError as exc:
            raise SecurityExceptionError(
                f"{category}[{entry_index}]: 'expires_at' must be an ISO "
                f"'YYYY-MM-DD' date, got {raw_expires!r}"
            ) from exc
    else:
        raise SecurityExceptionError(
            f"{category}[{entry_index}]: 'expires_at' is required"
        )
    return SecurityException(
        finding_id=finding_id,
        category=category,
        statement=statement,
        expires_at=expires_at,
    )


def validate_trivy_exceptions(
    path: Path,
    *,
    today: date | None = None,
) -> tuple[SecurityException, ...]:
    """Validate approved, expiring Trivy exceptions.

    Args:
        path: Path to a ``.trivyignore.yaml`` file.
        today: Validation date; defaults to :func:`datetime.date.today`.

    Returns:
        Every currently valid, unexpired exception.

    Raises:
        SecurityExceptionError: If the file is malformed, an entry is
            malformed, an entry has expired, or a ``(category, id)`` pair is
            duplicated.
    """
    active_today = today if today is not None else date.today()
    raw_document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_document, dict):
        raise SecurityExceptionError(f"{path}: document root must be a mapping")

    exceptions: list[SecurityException] = []
    seen: set[tuple[str, str]] = set()
    for category in _CATEGORIES:
        raw_entries = raw_document.get(category, [])
        if not isinstance(raw_entries, list):
            raise SecurityExceptionError(f"{category}: must be a list")
        for index, raw_entry in enumerate(raw_entries):
            entry = _parse_entry(raw_entry, category=category, entry_index=index)  # type: ignore[arg-type]
            key = (entry.category, entry.finding_id)
            if key in seen:
                raise SecurityExceptionError(
                    f"{category}[{index}]: duplicate exception for id "
                    f"{entry.finding_id!r}"
                )
            seen.add(key)
            if entry.expires_at < active_today:
                raise SecurityExceptionError(
                    f"{category}[{index}]: exception for {entry.finding_id!r} "
                    f"expired on {entry.expires_at.isoformat()}"
                )
            exceptions.append(entry)
    return tuple(exceptions)


__all__ = ["SecurityException", "SecurityExceptionError", "validate_trivy_exceptions"]
