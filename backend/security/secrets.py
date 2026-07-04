"""Small dependency-free secret scanner for CI and local development."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class SecretFinding:
    path: Path
    line: int
    kind: str
    match: str

    def render(self, root: Path) -> str:
        rel = self.path.relative_to(root) if self.path.is_relative_to(root) else self.path
        return f"{rel}:{self.line}: {self.kind} ({_mask(self.match)})"


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    ),
)

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "htmlcov",
    "node_modules",
}


def scan_path(root: Path | str) -> list[SecretFinding]:
    root_path = Path(root).resolve()
    findings: list[SecretFinding] = []
    for path in _iter_files(root_path):
        text = _read_text(path)
        if text is None:
            continue
        findings.extend(_scan_text(path, text))
    return findings


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    tracked = _git_tracked_files(root)
    if tracked is not None:
        yield from tracked
        return
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def _git_tracked_files(root: Path) -> list[Path] | None:
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    files: list[Path] = []
    for raw in result.stdout.split(b"\x00"):
        if not raw:
            continue
        rel = Path(raw.decode("utf-8", errors="ignore"))
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        path = root / rel
        if path.is_file():
            files.append(path)
    return files


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _scan_text(path: Path, text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in PATTERNS:
            for match in pattern.finditer(line):
                findings.append(
                    SecretFinding(
                        path=path,
                        line=line_no,
                        kind=kind,
                        match=match.group(0),
                    )
                )
    return findings


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan repository files for high-confidence secrets.")
    parser.add_argument("path", nargs="?", default=".", help="Path to scan.")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    findings = scan_path(root)
    if not findings:
        print("run_secret_scanning: no secrets found")
        return 0

    print("run_secret_scanning: potential secrets found", file=sys.stderr)
    for finding in findings:
        print(finding.render(root), file=sys.stderr)
    return 1


__all__ = ["SecretFinding", "main", "scan_path"]
