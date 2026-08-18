"""Tests for `autodev --version` build metadata (E34-S1-T2)."""

from __future__ import annotations

import json

import pytest

from backend.cli import main
from backend.ops.version import get_version_info


def test_version_flag_prints_json_metadata_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--version"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"version", "commit", "build_date"}
    assert payload["version"]


def test_get_version_info_falls_back_to_unknown_without_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTODEV_BUILD_COMMIT", raising=False)
    monkeypatch.delenv("AUTODEV_BUILD_DATE", raising=False)

    info = get_version_info()

    assert info.build_date == "unknown"
    assert info.commit  # either a real short hash from this repo, or "unknown"


def test_get_version_info_honors_build_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTODEV_BUILD_COMMIT", "deadbee")
    monkeypatch.setenv("AUTODEV_BUILD_DATE", "2026-08-18")

    info = get_version_info()

    assert info.commit == "deadbee"
    assert info.build_date == "2026-08-18"
    assert info.as_dict() == {
        "version": info.version,
        "commit": "deadbee",
        "build_date": "2026-08-18",
    }
