"""Tests for `autodev --shell` dispatch wiring (E14-S6).

The shell's own behavior (REPL loop, API-only contract) is covered by
`test_cli_shell_api_only.py`; this file only proves `backend/cli.py`
routes `--shell` into it correctly and that omitting both `--shell` and a
subcommand still fails exactly as it did before this story (a required
subcommand).
"""

from __future__ import annotations

import pytest

from backend.cli import build_parser, main


def test_shell_flag_coexists_with_the_subcommand_parser() -> None:
    parser = build_parser()

    shell_args = parser.parse_args(["--shell", "--mode", "approval", "--command", "do the thing"])
    assert shell_args.shell is True
    assert shell_args.mode == "approval"
    assert shell_args.shell_command == "do the thing"
    assert shell_args.command is None

    subcommand_args = parser.parse_args(["sessions", "list"])
    assert subcommand_args.shell is False
    assert subcommand_args.command == "sessions"


def test_main_dispatches_shell_flag_to_cli_shell_main(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_shell_main(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr("backend.cli_shell.main", fake_shell_main)

    exit_code = main(["--shell", "--mode", "hybrid", "--command", "goal text"])

    assert exit_code == 0
    assert calls == [["--mode", "hybrid", "--command", "goal text"]]


def test_main_without_shell_or_a_subcommand_still_errors(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2
    assert "a command is required" in capsys.readouterr().err
