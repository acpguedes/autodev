"""Behavioral tests for the GitHub branch-protection setup script."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _REPOSITORY_ROOT / "scripts" / "configure_branch_protection.sh"


def test_branch_protection_script_is_executable() -> None:
    """The documented direct invocation must be supported by the file mode."""
    assert _SCRIPT.stat().st_mode & stat.S_IXUSR


def test_branch_protection_script_sends_typed_json_payload(tmp_path: Path) -> None:
    """The GitHub API receives booleans, integers, arrays, and null as JSON types."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    arguments_file = tmp_path / "arguments.txt"
    body_file = tmp_path / "body.json"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$@" > "${GH_ARGUMENTS_FILE}"\n'
        'cat > "${GH_BODY_FILE}"\n',
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "GH_REPO": "example/autodev",
            "BRANCH": "main",
            "GH_ARGUMENTS_FILE": str(arguments_file),
            "GH_BODY_FILE": str(body_file),
        }
    )

    subprocess.run(
        ["bash", str(_SCRIPT)],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(body_file.read_text(encoding="utf-8"))
    assert payload == {
        "required_status_checks": {
            "strict": True,
            "contexts": [
                "lint-typecheck",
                "backend-tests",
                "patch-validation",
                "security-baseline",
                "frontend-checks",
                "smoke-e2e",
                "reference-eval-gate",
            ],
        },
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
        },
        "restrictions": None,
    }
    arguments = arguments_file.read_text(encoding="utf-8").splitlines()
    assert arguments[-2:] == ["--input", "-"]
