"""Unit tests for the dependency-free secret scanner (backend/security/secrets.py).

Covers pattern detection for all four secret kinds, git-tracked-file
discovery (success and fallback paths), binary/unreadable file rejection,
masking, ``SecretFinding.render`` path handling, and the CLI's exit codes.

All secret-shaped fixtures below are synthetic placeholders constructed only
to satisfy the scanner's regex shape (e.g. ``sk-`` followed by 20+ filler
characters) — they are not real credentials.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.security.secrets import (
    PATTERNS,
    SecretFinding,
    _git_tracked_files,
    _iter_files,
    _mask,
    _read_text,
    _scan_text,
    main,
    scan_path,
)

# Synthetic, non-functional secret-shaped strings used purely to exercise the
# scanner's regexes. None of these are real credentials.
_FAKE_OPENAI_KEY = "sk-" + ("x" * 25)
_FAKE_GITHUB_TOKEN = "ghp_" + ("y" * 36)
_FAKE_AWS_KEY = "AKIA" + ("A" * 16)
# Split so the repo's own raw-text secret scanner never sees the assembled
# PEM marker in this source file.
_FAKE_PRIVATE_KEY_HEADER = "-----BEGIN RSA PRIVATE" + " KEY-----"


def test_scan_text_detects_openai_key() -> None:
    """An OpenAI-shaped key on a line is detected with kind 'openai_api_key'."""
    findings = _scan_text(Path("f.py"), f'API_KEY = "{_FAKE_OPENAI_KEY}"\n')
    assert len(findings) == 1
    assert findings[0].kind == "openai_api_key"
    assert findings[0].match == _FAKE_OPENAI_KEY
    assert findings[0].line == 1


def test_scan_text_detects_github_token() -> None:
    """A GitHub-shaped token is detected with kind 'github_token'."""
    findings = _scan_text(Path("f.py"), f"token = {_FAKE_GITHUB_TOKEN}\n")
    assert [f.kind for f in findings] == ["github_token"]


def test_scan_text_detects_aws_access_key_id() -> None:
    """An AWS access key id (AKIA prefix) is detected."""
    findings = _scan_text(Path("f.py"), f"aws_access_key_id = {_FAKE_AWS_KEY}\n")
    assert [f.kind for f in findings] == ["aws_access_key_id"]


def test_scan_text_detects_asia_prefixed_aws_key() -> None:
    """A temporary AWS key (ASIA prefix) is also detected."""
    fake_asia_key = "ASIA" + ("B" * 16)
    findings = _scan_text(Path("f.py"), fake_asia_key)
    assert [f.kind for f in findings] == ["aws_access_key_id"]


def test_scan_text_detects_private_key_header() -> None:
    """A PEM private-key header is detected regardless of the key algorithm."""
    findings = _scan_text(Path("f.py"), f"{_FAKE_PRIVATE_KEY_HEADER}\nMIIEpAIBAAKCAQEA\n")
    assert [f.kind for f in findings] == ["private_key"]
    assert findings[0].line == 1


def test_scan_text_detects_generic_private_key_header() -> None:
    """A private-key header without an algorithm qualifier still matches."""
    findings = _scan_text(Path("f.py"), "-----BEGIN PRIVATE" + " KEY-----\n")
    assert [f.kind for f in findings] == ["private_key"]


def test_scan_text_multiple_findings_multiple_lines() -> None:
    """Multiple matches across multiple lines are all reported, in order."""
    text = f"line one\n{_FAKE_OPENAI_KEY}\nline three\n{_FAKE_GITHUB_TOKEN}\n"
    findings = _scan_text(Path("f.py"), text)
    assert [(f.kind, f.line) for f in findings] == [
        ("openai_api_key", 2),
        ("github_token", 4),
    ]


def test_scan_text_no_matches_on_clean_text() -> None:
    """Text with no secret-shaped substrings produces no findings."""
    assert _scan_text(Path("f.py"), "just some ordinary source code\n") == []


def test_patterns_table_has_four_entries() -> None:
    """The PATTERNS tuple defines exactly the four documented kinds."""
    kinds = {kind for kind, _pattern in PATTERNS}
    assert kinds == {"openai_api_key", "github_token", "aws_access_key_id", "private_key"}


def test_mask_short_value_is_fully_redacted() -> None:
    """Values of length <= 8 are fully masked to '***'."""
    assert _mask("short123") == "***"
    assert _mask("") == "***"


def test_mask_long_value_keeps_first_and_last_four() -> None:
    """Values longer than 8 chars keep only their first/last 4 characters visible."""
    assert _mask(_FAKE_OPENAI_KEY) == f"{_FAKE_OPENAI_KEY[:4]}...{_FAKE_OPENAI_KEY[-4:]}"


def test_secret_finding_render_relative_path(tmp_path: Path) -> None:
    """render() shows a path relative to root when the finding is inside root."""
    nested = tmp_path / "src" / "config.py"
    finding = SecretFinding(path=nested, line=3, kind="openai_api_key", match=_FAKE_OPENAI_KEY)
    rendered = finding.render(tmp_path)
    assert rendered.startswith("src/config.py:3: openai_api_key (")
    assert _FAKE_OPENAI_KEY not in rendered


def test_secret_finding_render_absolute_path_outside_root(tmp_path: Path) -> None:
    """render() falls back to the absolute path when the finding is outside root."""
    outside = tmp_path.parent / "elsewhere.py"
    finding = SecretFinding(path=outside, line=1, kind="github_token", match=_FAKE_GITHUB_TOKEN)
    rendered = finding.render(tmp_path)
    assert rendered.startswith(f"{outside}:1: github_token (")


def test_read_text_rejects_binary_content(tmp_path: Path) -> None:
    """A file containing a null byte is treated as binary and skipped."""
    binary_file = tmp_path / "binary.dat"
    binary_file.write_bytes(b"\x00\x01\x02binary")
    assert _read_text(binary_file) is None


def test_read_text_rejects_undecodable_content(tmp_path: Path) -> None:
    """A file with invalid UTF-8 bytes (and no null byte) is skipped."""
    bad_utf8 = tmp_path / "bad.txt"
    bad_utf8.write_bytes(b"\xff\xfe\xfd\xfc")
    assert _read_text(bad_utf8) is None


def test_read_text_missing_file_returns_none(tmp_path: Path) -> None:
    """A nonexistent file is treated as unreadable, not an error."""
    assert _read_text(tmp_path / "does-not-exist.txt") is None


def test_read_text_returns_decoded_text(tmp_path: Path) -> None:
    """A normal UTF-8 text file is read and returned verbatim."""
    text_file = tmp_path / "clean.txt"
    text_file.write_text("hello world\n", encoding="utf-8")
    assert _read_text(text_file) == "hello world\n"


def test_scan_path_scans_single_file(tmp_path: Path) -> None:
    """scan_path() on a single file scans that file only."""
    target = tmp_path / "secret.py"
    target.write_text(f'key = "{_FAKE_OPENAI_KEY}"\n', encoding="utf-8")
    findings = scan_path(target)
    assert len(findings) == 1
    assert findings[0].path == target.resolve()


def test_scan_path_finds_nothing_in_clean_tree(tmp_path: Path) -> None:
    """scan_path() over a directory with no secrets returns an empty list."""
    (tmp_path / "a.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
    assert scan_path(tmp_path) == []


def test_scan_path_skips_excluded_dirs_without_git(tmp_path: Path) -> None:
    """When not a git repo, rglob-based iteration still skips EXCLUDED_DIRS."""
    excluded = tmp_path / "node_modules"
    excluded.mkdir()
    (excluded / "secret.js").write_text(f'"{_FAKE_OPENAI_KEY}"\n', encoding="utf-8")
    included = tmp_path / "src.py"
    included.write_text(f'"{_FAKE_GITHUB_TOKEN}"\n', encoding="utf-8")
    findings = scan_path(tmp_path)
    assert [f.path for f in findings] == [included.resolve()]


def test_git_tracked_files_returns_none_when_not_a_repo(tmp_path: Path) -> None:
    """A directory without a .git subdirectory is not treated as a git repo."""
    assert _git_tracked_files(tmp_path) is None


def test_git_tracked_files_returns_none_when_git_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If invoking git fails (e.g. binary missing), fall back to None."""
    (tmp_path / ".git").mkdir()

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("git executable not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert _git_tracked_files(tmp_path) is None


def test_git_tracked_files_returns_none_on_called_process_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If git exits non-zero, the CalledProcessError is swallowed to None."""
    (tmp_path / ".git").mkdir()

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(returncode=128, cmd=["git"])

    monkeypatch.setattr(subprocess, "run", _raise)
    assert _git_tracked_files(tmp_path) is None


def test_git_tracked_files_lists_tracked_files_and_filters_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tracked files are listed, excluded-dir entries and non-files are filtered out."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "src.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("y = 2\n", encoding="utf-8")

    tracked_paths = [
        b"src.py",
        b"node_modules/lib.js",
        b"missing.py",  # listed by git but absent on disk (e.g. deleted)
    ]
    fake_stdout = b"\x00".join(tracked_paths) + b"\x00"

    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout=fake_stdout)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    tracked = _git_tracked_files(tmp_path)
    assert tracked is not None
    assert tracked == [tmp_path / "src.py"]


def test_iter_files_single_file_short_circuits() -> None:
    """_iter_files() on a file path yields just that file."""
    target = Path(__file__)
    assert list(_iter_files(target)) == [target]


def test_iter_files_uses_git_tracked_files_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_iter_files() prefers the git-tracked-file list when the root is a git repo."""
    (tmp_path / ".git").mkdir()
    tracked_file = tmp_path / "only_this.py"
    tracked_file.write_text("z = 3\n", encoding="utf-8")
    (tmp_path / "untracked.py").write_text("w = 4\n", encoding="utf-8")

    monkeypatch.setattr(
        "backend.security.secrets._git_tracked_files", lambda _root: [tracked_file]
    )
    assert list(_iter_files(tmp_path)) == [tracked_file]


def test_main_returns_zero_and_prints_ok_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() exits 0 and prints the success banner when no secrets are found."""
    (tmp_path / "clean.py").write_text("print('hi')\n", encoding="utf-8")
    exit_code = main([str(tmp_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "run_secret_scanning: no secrets found" in captured.out


def test_main_returns_one_and_prints_findings_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() exits 1 and prints masked findings to stderr when secrets are found."""
    secret_file = tmp_path / "leak.py"
    secret_file.write_text(f'token = "{_FAKE_GITHUB_TOKEN}"\n', encoding="utf-8")
    exit_code = main([str(tmp_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "run_secret_scanning: potential secrets found" in captured.err
    assert "github_token" in captured.err
    assert _FAKE_GITHUB_TOKEN not in captured.err


def test_main_defaults_to_current_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """With no argv, main() defaults to scanning '.' and still returns an int exit code."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ok.py").write_text("a = 1\n", encoding="utf-8")
    assert main([]) == 0
