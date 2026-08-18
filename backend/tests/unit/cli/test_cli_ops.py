"""Tests for the `autodev doctor` / `autodev bootstrap` subcommands (E34-S2)."""

from __future__ import annotations

import json

import pytest

from backend.cli import build_parser, main
from backend.ops.bootstrap import BootstrapResult
from backend.ops.doctor import DiagnosticCheck
from backend.ops.upgrade import UpgradeResult


def test_doctor_and_bootstrap_subcommands_parse() -> None:
    parser = build_parser()

    doctor_args = parser.parse_args(["doctor"])
    assert doctor_args.command == "doctor"

    bootstrap_args = parser.parse_args(["bootstrap"])
    assert bootstrap_args.command == "bootstrap"

    upgrade_args = parser.parse_args(
        ["upgrade", "--backup-dir", "/tmp/x", "--target-version", "v1"]
    )
    assert upgrade_args.command == "upgrade"
    assert upgrade_args.backup_dir == "/tmp/x"
    assert upgrade_args.target_version == "v1"


def test_doctor_handler_exits_zero_when_all_checks_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checks = (DiagnosticCheck("settings", "ok", "fine"),)
    monkeypatch.setattr("backend.ops.doctor.run_diagnostics", lambda: checks)

    exit_code = main(["doctor"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["checks"][0]["name"] == "settings"


def test_doctor_handler_exits_nonzero_when_a_check_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checks = (DiagnosticCheck("settings", "fail", "broken"),)
    monkeypatch.setattr("backend.ops.doctor.run_diagnostics", lambda: checks)

    exit_code = main(["doctor"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"


def test_bootstrap_handler_exits_zero_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = BootstrapResult(
        status="ok",
        checks=(DiagnosticCheck("settings", "ok", "fine"),),
        profile="local",
        storage_backend="local",
    )
    monkeypatch.setattr("backend.ops.bootstrap.bootstrap", lambda: result)

    exit_code = main(["bootstrap"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["profile"] == "local"


def test_bootstrap_handler_exits_nonzero_on_preflight_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = BootstrapResult(
        status="fail", checks=(DiagnosticCheck("settings", "fail", "broken"),)
    )
    monkeypatch.setattr("backend.ops.bootstrap.bootstrap", lambda: result)

    exit_code = main(["bootstrap"])

    assert exit_code == 1


def test_upgrade_handler_exits_zero_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = UpgradeResult(status="ok", detail="applied", backup_dir="/tmp/backup")
    captured: dict[str, object] = {}

    def _fake_run_upgrade(backup_dir, target_version=None):
        captured["backup_dir"] = backup_dir
        captured["target_version"] = target_version
        return result

    monkeypatch.setattr("backend.ops.upgrade.run_upgrade", _fake_run_upgrade)

    exit_code = main(["upgrade", "--backup-dir", "/tmp/backup", "--target-version", "v1"])

    assert exit_code == 0
    assert captured == {"backup_dir": "/tmp/backup", "target_version": "v1"}
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"


def test_upgrade_handler_exits_nonzero_when_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = UpgradeResult(status="refused", detail="database schema is newer")
    monkeypatch.setattr(
        "backend.ops.upgrade.run_upgrade", lambda backup_dir, target_version=None: result
    )

    exit_code = main(["upgrade"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "refused"
