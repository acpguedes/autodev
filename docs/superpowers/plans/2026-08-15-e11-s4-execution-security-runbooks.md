# E11-S4 Execution Security and Runbooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close E11-S4 by enforcing least-privilege execution and plugin policy, protecting configuration credentials, gating secret/dependency/license findings, making configured backups fail closed and observable, and shipping actionable incident/restore alerts and runbooks.

**Architecture:** Centralize sandbox decisions in a typed immutable policy derived from `Settings`; keep Docker as the current execution boundary; treat in-process plugins as trusted core-equivalent code and reject unsafe production installations without changing `plugin.yaml`; keep secrets environment-backed while redacting every exposed credential; reuse E8 backup tooling and E11-S1 OpenTelemetry/Prometheus infrastructure; add OSS Alertmanager under the existing observability profile.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic Settings, Docker, pytest, OpenTelemetry, Prometheus, Alertmanager, Trivy, PyYAML, GitHub Actions.

**Spec:** `docs/v2_platform/phases/e11_observability_security_multitenant.md` E11-S4; `docs/architecture/v2_platform_reference.md` §18.7.5, §16.1.2–§16.1.5, and §17.4.

## Global Constraints

- Execute on `story/e11-s4-execution-security`, cut from the E11 epic branch after E11-S1 has landed.
- Activate `.venv` before every local Python, pytest, Ruff, mypy, or script command.
- Reuse E11-S1 exactly:
  - `backend.observability.runtime.get_meter(scope: str = "backend.observability") -> opentelemetry.metrics.Meter`
  - `infrastructure/observability/prometheus.yaml`
  - `infrastructure/observability/prometheus-rules.yml`
  - the existing Collector → Prometheus pipeline.
- Prometheus loads the shared rules file at `/etc/prometheus/prometheus-rules.yml`; append S4 alert groups without renaming or duplicating the file.
- Do not restore or extend the legacy in-process Prometheus registry.
- Do not implement E32 execution-environment profiles, backend selection, workspace lifecycle, per-profile network/filesystem allowlists, or execution audit records.
- Do not implement E33 secret-store abstractions, encrypted storage, scoped secret references, injection, rotation, revocation, or secret audit events.
- Do not change `RuntimeSpec`, `PermissionSpec`, `PluginManifest`, `plugin.yaml`, or `hostApi`. ADR-020 records a host security policy, not a schema change.
- In-process plugin code is trusted-only. Production rejects both:
  - plugin IDs not explicitly trusted by the operator; and
  - in-process plugins requesting network, filesystem, command execution, or secret capabilities.
- Local in-process development remains compatible, with the existing permission broker still deny-by-default.
- Docker remains networkless by default. A non-`none` Docker network remains an explicit operator override; E11-S4 does not invent E32-style allowlists.
- Never place secret values in logs, traces, metrics, alerts, exception messages, test output, or documentation.
- SCA fails for `HIGH` and `CRITICAL` vulnerability or license findings unless an unexpired, approved exception exists.
- The real Docker network-denial contract must run and pass in CI; a skipped test does not satisfy E11-S4 DoD.
- Alertmanager is optional OSS infrastructure under the existing `observability` Compose profile. No paid notification service is required.
- Plugin signing/hash verification remains owned by E13. Fleet-wide container digest pinning and broad SAST expansion remain their existing supply-chain/E12 follow-ups; this story must not claim those gaps are closed.
- Story validation is scoped to affected tests plus shared type/lint contracts. The full `make check` gate runs on the epic-to-`main` PR.

## File Map

| Responsibility | Files |
| --- | --- |
| Plugin security decision and enforcement | `docs/v2_platform/decisions/ADR-020-trusted-in-process-plugin-boundary.md`, `docs/v2_platform/decisions/README.md`, `backend/config/settings.py`, `backend/plugins/host.py`, `.env.example`, plugin/settings tests |
| Typed Docker sandbox and escape contract | `backend/validation/models.py`, `backend/validation/sandbox.py`, `backend/validation/__init__.py`, sandbox unit/integration tests, `.github/workflows/ci-backend.yml` |
| Secret/SCA gates | `backend/security/secrets.py`, `backend/security/exceptions.py`, `scripts/validate_security_exceptions.py`, `.trivyignore.yaml`, `Makefile`, CI workflow, security tests |
| Credential redaction and deployment defaults | `backend/config/settings.py`, `backend/api/routers/features.py`, `infrastructure/docker-compose.yml`, `.env.example`, config/infrastructure tests |
| Fail-closed backup and metrics | `backend/persistence/backup.py`, `backend/persistence/backup_status.py`, `backend/observability/backup_metrics.py`, `backend/api/main.py`, settings/Compose, backup/metrics tests |
| Alerts, runbooks, completion evidence | S1 Prometheus assets, Alertmanager assets, operations/security/config docs, E8/E11 runbooks, phase/progress trackers |

---

## Task 1: Record and enforce the trusted-only in-process plugin boundary

**Files:**

- Create: `docs/v2_platform/decisions/ADR-020-trusted-in-process-plugin-boundary.md`
- Modify: `docs/v2_platform/decisions/README.md`
- Modify: `backend/config/settings.py`
- Modify: `backend/plugins/host.py`
- Modify: `.env.example`
- Modify: `backend/tests/unit/plugins/test_plugins_host.py`
- Modify: `backend/tests/unit/config/test_settings.py`

**Interfaces:**

```python
class Settings(BaseSettings):
    autodev_trusted_in_process_plugins: str = ""

    def trusted_in_process_plugin_ids(self) -> frozenset[str]:
        """Return operator-trusted in-process plugin identifiers."""
```

```python
class PluginHost:
    def __init__(
        self,
        *,
        store: Any | None = None,
        plugin_dirs: Iterable[Path | str] = (),
        host_api_version: str = HOST_API_VERSION,
        workspace: Path | str = ".",
        secrets: dict[str, str] | None = None,
        production_mode: bool | None = None,
        trusted_in_process_plugins: Iterable[str] | None = None,
    ) -> None:
        """Initialize the plugin host and production trust policy."""
```

```python
def _privileged_in_process_permissions(
    manifest: PluginManifest,
) -> tuple[str, ...]:
    """Return sensitive permission names requested by an in-process plugin."""
```

### RED

- [ ] Extend the plugin test helper so tests can supply a manifest permission block and optional `runtime.isolation`.

- [ ] Add these tests:

```python
def test_production_rejects_untrusted_in_process_plugin(
    tmp_path: Path,
) -> None:
    plugin_dir = _write_plugin(tmp_path, "untrusted-plugin")
    host = PluginHost(
        store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"),
        production_mode=True,
        trusted_in_process_plugins=(),
    )

    record = host.install(plugin_dir)

    assert record.state is PluginState.REJECTED
    assert record.reason == (
        "production requires an explicit operator trust grant for "
        "in-process plugin acme/untrusted-plugin"
    )


def test_production_rejects_privileged_trusted_in_process_plugin(
    tmp_path: Path,
) -> None:
    plugin_dir = _write_plugin(
        tmp_path,
        "network-plugin",
        permissions_yaml=(
            "network:\n"
            "  egress:\n"
            "    - api.example.com:443"
        ),
    )
    host = PluginHost(
        store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"),
        production_mode=True,
        trusted_in_process_plugins=("acme/network-plugin",),
    )

    record = host.install(plugin_dir)

    assert record.state is PluginState.REJECTED
    assert "permissions.network.egress" in record.reason


def test_production_accepts_explicitly_trusted_unprivileged_plugin(
    tmp_path: Path,
) -> None:
    plugin_dir = _write_plugin(tmp_path, "trusted-plugin")
    host = PluginHost(
        store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"),
        production_mode=True,
        trusted_in_process_plugins=("acme/trusted-plugin",),
    )

    assert host.install(plugin_dir).state is PluginState.INSTALLED


def test_local_mode_preserves_current_in_process_behavior(
    tmp_path: Path,
) -> None:
    plugin_dir = _write_plugin(
        tmp_path,
        "local-plugin",
        permissions_yaml=(
            "filesystem:\n"
            "  read:\n"
            "    - ${workspace}"
        ),
    )
    host = PluginHost(
        store=DurableStore(f"sqlite:///{tmp_path / 'plugins.db'}"),
        production_mode=False,
        trusted_in_process_plugins=(),
    )

    assert host.install(plugin_dir).state is PluginState.INSTALLED
```

- [ ] Add a settings parser test:

```python
def test_trusted_in_process_plugin_ids_are_normalized() -> None:
    settings = Settings(
        autodev_trusted_in_process_plugins="acme/one, acme/two,acme/one"
    )

    assert settings.trusted_in_process_plugin_ids() == frozenset(
        {"acme/one", "acme/two"}
    )
```

- [ ] Run:

```bash
source .venv/bin/activate && python -m pytest \
  backend/tests/unit/plugins/test_plugins_host.py \
  backend/tests/unit/config/test_settings.py -q
```

Expected: failures because the constructor arguments, setting, parser, and production rejection policy do not exist.

### GREEN

- [ ] Add the typed setting and parser:

```python
def trusted_in_process_plugin_ids(self) -> frozenset[str]:
    """Parse the operator trust allowlist for in-process plugins.

    Returns:
        Normalized, non-empty plugin identifiers.
    """
    return frozenset(
        plugin_id.strip()
        for plugin_id in self.autodev_trusted_in_process_plugins.split(",")
        if plugin_id.strip()
    )
```

- [ ] Implement the sensitive-capability classifier:

```python
def _privileged_in_process_permissions(
    manifest: PluginManifest,
) -> tuple[str, ...]:
    """Return sensitive permissions that require a real isolation boundary.

    Args:
        manifest: Parsed plugin manifest.

    Returns:
        Canonical names of requested privileged permission blocks.
    """
    permissions = manifest.permissions
    requested: list[str] = []
    if permissions.network_egress:
        requested.append("permissions.network.egress")
    if permissions.filesystem_read:
        requested.append("permissions.filesystem.read")
    if permissions.filesystem_write:
        requested.append("permissions.filesystem.write")
    if permissions.exec_commands:
        requested.append("permissions.exec.commands")
    if permissions.secrets:
        requested.append("permissions.secrets")
    return tuple(requested)
```

- [ ] Resolve constructor defaults from `Settings` only when not explicitly injected, then extend `_compatibility_reason`:

```python
def _production_in_process_reason(
    self,
    manifest: PluginManifest,
) -> str:
    """Return a production rejection reason for an unsafe in-process plugin."""
    if not self._production_mode or manifest.runtime.loader != "in-process":
        return ""

    if manifest.id not in self._trusted_in_process_plugins:
        return (
            "production requires an explicit operator trust grant for "
            f"in-process plugin {manifest.id}"
        )

    if manifest.runtime.isolation not in {None, "none"}:
        return (
            "the in-process loader cannot satisfy runtime.isolation="
            f"{manifest.runtime.isolation!r}"
        )

    privileged = _privileged_in_process_permissions(manifest)
    if privileged:
        return (
            "production rejects privileged permissions for trusted in-process "
            f"plugins: {', '.join(privileged)}"
        )
    return ""
```

`_compatibility_reason` must return this reason before installation. Rejection uses the existing `PluginState.REJECTED` persistence and event behavior.

- [ ] Add `AUTODEV_TRUSTED_IN_PROCESS_PLUGINS=` to `.env.example`.

- [ ] Write ADR-020 with:

  - **Status:** Accepted
  - **Date:** 2026-08-15
  - **Related epic:** E11-S4
  - Context: the permission broker is capability mediation, while Python in-process loading is not a security boundary.
  - Decision: operator allowlist plus unconditional production rejection of sensitive grants.
  - Explicit statement that host API/event grants remain brokered and do not make a plugin privileged for this rule.
  - Explicit statement that the manifest schema and `hostApi` remain unchanged.
  - Alternatives rejected:
    1. self-asserted `trusted: true` manifest field;
    2. relying on import interception as isolation;
    3. rejecting every bundled in-process plugin in production.
  - Safe rollback: reject all in-process production plugins until an isolated loader is available.
  - References to E11-S4 and canonical §16.1.4–§16.1.5.

- [ ] Add this index row, preserving ADR-020 even if ADR-017–ADR-019 land concurrently:

```markdown
| ADR-020 | Trusted-Only In-Process Plugin Boundary | Accepted | E11-S4 | 2026-08-15 |
```

- [ ] Run the same targeted tests.

Expected: all pass, including existing manifest contract tests.

- [ ] Commit:

```bash
git add docs/v2_platform/decisions backend/config/settings.py backend/plugins/host.py \
  backend/tests/unit/plugins/test_plugins_host.py \
  backend/tests/unit/config/test_settings.py .env.example
git commit -m "fix(e11): enforce trusted in-process plugin boundary"
```

---

## Task 2: Replace raw sandbox environment checks with a typed, mounted security boundary

**Files:**

- Modify: `backend/config/settings.py`
- Modify: `backend/validation/models.py`
- Modify: `backend/validation/sandbox.py`
- Modify: `backend/validation/__init__.py`
- Modify: `backend/tests/unit/validation/test_sandbox_runner.py`
- Create: `backend/tests/integration/test_sandbox_security_contract.py`
- Modify: `.github/workflows/ci-backend.yml`

**Interfaces:**

```python
@dataclass(frozen=True)
class SandboxPolicy:
    """Typed execution policy for the current Docker sandbox."""

    enabled: bool
    allow_local: bool
    docker_network: str
    project_root: Path
    timeout_seconds: int
```

```python
class SandboxPolicyError(ValueError):
    """Raised when a validation job violates the sandbox policy."""
```

```python
def sandbox_policy_from_settings(
    settings: Settings | None = None,
) -> SandboxPolicy:
    """Build the typed sandbox policy from centralized settings."""
```

```python
class SandboxRunner:
    def __init__(
        self,
        allowed_commands: Sequence[str] | None = None,
        *,
        policy: SandboxPolicy | None = None,
    ) -> None:
        """Initialize a runner with an explicit or settings-derived policy."""
```

### RED

- [ ] Add `autodev_sandbox_timeout_seconds: int = Field(default=300, ge=1, le=3600)` to the expected settings contract in tests.

- [ ] Add truthiness tests using actual environment parsing:

```python
@pytest.mark.parametrize("raw", ["0", "false", "False"])
def test_sandbox_false_environment_values_disable_execution(
    raw: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTODEV_ENABLE_SANDBOX", raw)
    settings = Settings()

    assert sandbox_policy_from_settings(settings).enabled is False
```

- [ ] Replace environment mutation in existing runner tests with explicit `SandboxPolicy` injection.

- [ ] Add unit tests asserting:

  - `cwd="../outside"` returns `backend="blocked"` without spawning a process;
  - the resolved workspace is mounted read-only at `/workspace`;
  - Docker receives `--network=none`;
  - the container runs as `65534:65534`;
  - `cap-drop=ALL`, `no-new-privileges`, PID, memory, and CPU limits remain present;
  - the container root filesystem is read-only with a bounded `/tmp`;
  - timeout returns code `124` with a sanitized message;
  - no Docker plus `allow_local=False` fails closed;
  - local execution is possible only with `allow_local=True` and still uses the guarded workspace.

```python
def test_docker_command_mounts_only_guarded_workspace(
    tmp_path: Path,
) -> None:
    completed = MagicMock(returncode=0, stdout="", stderr="")
    runner = SandboxRunner(
        allowed_commands=("python",),
        policy=SandboxPolicy(
            enabled=True,
            allow_local=False,
            docker_network="none",
            project_root=tmp_path,
            timeout_seconds=30,
        ),
    )

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", return_value=completed) as run,
    ):
        runner.run(
            ValidationJob(
                job_id="mounted",
                command=["python", "-c", "print('ok')"],
                cwd=".",
            )
        )

    command = run.call_args.args[0]
    assert "--network=none" in command
    assert (
        f"type=bind,source={tmp_path.resolve()},target=/workspace,readonly"
        in command
    )
    assert "--read-only" in command
    assert "--user=65534:65534" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges" in command
```

- [ ] Add real Docker contract tests:

```python
@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker is required for the sandbox security contract",
)
def test_docker_sandbox_denies_network_by_default(tmp_path: Path) -> None:
    runner = _docker_runner(tmp_path)
    result = runner.run(
        ValidationJob(
            job_id="network-denied",
            command=[
                "python",
                "-c",
                (
                    "import socket; "
                    "socket.create_connection(('1.1.1.1', 53), timeout=1)"
                ),
            ],
            cwd=".",
        )
    )

    assert result.backend == "docker"
    assert result.returncode != 0


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker is required for the sandbox security contract",
)
def test_docker_sandbox_exposes_workspace_but_not_host_sibling(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "visible.txt").write_text("visible", encoding="utf-8")
    (tmp_path / "host-only.txt").write_text("hidden", encoding="utf-8")
    runner = _docker_runner(workspace)

    result = runner.run(
        ValidationJob(
            job_id="filesystem",
            command=[
                "python",
                "-c",
                (
                    "from pathlib import Path; "
                    "assert Path('/workspace/visible.txt').read_text() == 'visible'; "
                    "assert not Path('/host-only.txt').exists()"
                ),
            ],
            cwd=".",
        )
    )

    assert result.returncode == 0


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker is required for the sandbox security contract",
)
def test_docker_sandbox_cannot_escalate_to_root(tmp_path: Path) -> None:
    runner = _docker_runner(tmp_path)
    result = runner.run(
        ValidationJob(
            job_id="privilege",
            command=[
                "python",
                "-c",
                (
                    "import os; assert os.geteuid() == 65534; "
                    "\ntry:\n os.setuid(0)\nexcept PermissionError:\n pass"
                    "\nelse:\n raise SystemExit(9)"
                ),
            ],
            cwd=".",
        )
    )

    assert result.returncode == 0
```

- [ ] Run unit tests.

Expected: failures because raw strings are still tested directly, `SandboxPolicy` does not exist, workspace paths are not validated or mounted, and timeout/root filesystem controls are absent.

### GREEN

- [ ] Implement settings conversion:

```python
def sandbox_policy_from_settings(
    settings: Settings | None = None,
) -> SandboxPolicy:
    """Build the current Docker sandbox policy from typed settings.

    Args:
        settings: Optional settings instance; defaults to the cached settings.

    Returns:
        An immutable sandbox policy.
    """
    active = settings or get_settings()
    project_root = Path(
        active.autodev_project_root.strip() or "."
    ).expanduser().resolve()
    return SandboxPolicy(
        enabled=active.autodev_enable_sandbox,
        allow_local=active.autodev_sandbox_allow_local,
        docker_network=(
            active.autodev_sandbox_docker_network.strip() or "none"
        ),
        project_root=project_root,
        timeout_seconds=active.autodev_sandbox_timeout_seconds,
    )
```

- [ ] Remove every direct `os.environ.get` call from `SandboxRunner`.

- [ ] Guard `cwd` before either Docker or local execution:

```python
def _resolve_workspace(self, cwd: str) -> Path:
    candidate = Path(cwd).expanduser()
    if not candidate.is_absolute():
        candidate = self._policy.project_root / candidate
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(self._policy.project_root)
    except ValueError as exc:
        raise SandboxPolicyError(
            "validation cwd is outside AUTODEV_PROJECT_ROOT"
        ) from exc
    if not resolved.is_dir():
        raise SandboxPolicyError("validation cwd must be a directory")
    return resolved
```

Return a typed blocked `ValidationResult` from `run()` when this raises.

- [ ] Build the Docker command with these exact controls:

```python
docker_cmd = [
    "docker",
    "run",
    "--rm",
    f"--network={self._policy.docker_network}",
    "--user=65534:65534",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--pids-limit=256",
    "--memory=512m",
    "--cpus=1",
    "--read-only",
    "--tmpfs=/tmp:rw,noexec,nosuid,size=256m",
    "--env",
    "HOME=/tmp",
    "--env",
    "PYTHONDONTWRITEBYTECODE=1",
    "--mount",
    f"type=bind,source={workspace},target=/workspace,readonly",
    "--workdir=/workspace",
    _DOCKER_IMAGE,
    *job.command,
]
```

Pass `timeout=self._policy.timeout_seconds` and `check=False`. Convert `subprocess.TimeoutExpired` into return code `124`.

- [ ] Use the same resolved workspace for explicit local fallback. Do not pass a widened environment or introduce another backend abstraction.

- [ ] Export `SandboxPolicy`, `SandboxPolicyError`, and `sandbox_policy_from_settings`.

- [ ] Add a mandatory CI step to the security job:

```yaml
- name: Install backend dependencies
  run: python -m pip install -r backend/requirements.txt

- name: Run Docker sandbox security contract
  run: |
    docker pull python:3.11-slim
    python -m pytest backend/tests/integration/test_sandbox_security_contract.py -q -rs
```

The CI log must report passed tests, not skips.

- [ ] Run:

```bash
source .venv/bin/activate && python -m pytest \
  backend/tests/unit/validation/test_sandbox_runner.py \
  backend/tests/unit/validation/test_validation_api.py -q
docker pull python:3.11-slim
source .venv/bin/activate && python -m pytest \
  backend/tests/integration/test_sandbox_security_contract.py -q -rs
```

Expected: unit tests pass; the Docker contract reports three passed tests and zero skips.

- [ ] Commit:

```bash
git add backend/config/settings.py backend/validation \
  backend/tests/unit/validation \
  backend/tests/integration/test_sandbox_security_contract.py \
  .github/workflows/ci-backend.yml
git commit -m "fix(e11): harden the typed validation sandbox"
```

---

## Task 3: Establish a clean secret baseline and HIGH/CRITICAL vulnerability-license gate

**Files:**

- Modify: `backend/security/secrets.py`
- Create: `backend/security/exceptions.py`
- Create: `scripts/validate_security_exceptions.py`
- Create: `.trivyignore.yaml`
- Modify: `backend/tests/unit/security/test_secrets.py`
- Create: `backend/tests/unit/security/test_security_exceptions.py`
- Create: `backend/tests/unit/security/test_ci_security_policy.py`
- Modify: `backend/tests/unit/observability/test_model_tracing.py`
- Modify: `Makefile`
- Modify: `.github/workflows/ci-backend.yml`

**Interfaces:**

```python
def _git_scannable_files(root: Path) -> list[Path] | None:
    """Return tracked and untracked, non-ignored repository files."""
```

```python
@dataclass(frozen=True)
class SecurityException:
    finding_id: str
    category: Literal["vulnerabilities", "licenses"]
    statement: str
    expires_at: date
```

```python
class SecurityExceptionError(ValueError):
    """Raised when a Trivy exception is malformed or expired."""
```

```python
def validate_trivy_exceptions(
    path: Path,
    *,
    today: date | None = None,
) -> tuple[SecurityException, ...]:
    """Validate approved, expiring Trivy exceptions."""
```

### RED

- [ ] Capture the current repository baseline once:

```bash
source .venv/bin/activate && python scripts/run_secret_scanning.py .
```

Expected: exit `1`, currently identifying the three contiguous synthetic `sk-` test values in `backend/tests/unit/observability/test_model_tracing.py`. The output must already mask the matched value.

- [ ] Add a test proving an untracked, non-ignored file is scanned:

```python
def test_scan_path_includes_untracked_nonignored_files(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("safe\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "tracked.txt"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    token = "sk-" + ("A" * 24)
    (tmp_path / "pending.txt").write_text(token, encoding="utf-8")
    (tmp_path / "ignored.txt").write_text(token, encoding="utf-8")

    findings = scan_path(tmp_path)

    assert [finding.path.name for finding in findings] == ["pending.txt"]
```

- [ ] Add exception validation tests for:

  - empty vulnerability/license lists;
  - a valid future exception;
  - missing `statement`;
  - statement without `approved-by=` and `reason=`;
  - malformed ISO date;
  - expired exception;
  - duplicate category/ID pairs.

```python
def test_expired_security_exception_is_rejected(tmp_path: Path) -> None:
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
```

- [ ] Add a CI policy test that parses `.github/workflows/ci-backend.yml` and asserts:

  - scanners contain both `vuln` and `license`;
  - severity is exactly `HIGH,CRITICAL`;
  - `exit-code` is `"1"`;
  - `ignore-unfixed` is false;
  - `.trivyignore.yaml` is passed;
  - exception validation runs before Trivy.

- [ ] Run:

```bash
source .venv/bin/activate && python -m pytest \
  backend/tests/unit/security/test_secrets.py \
  backend/tests/unit/security/test_security_exceptions.py \
  backend/tests/unit/security/test_ci_security_policy.py -q
```

Expected: failures because untracked files are omitted and the exception policy does not exist.

### GREEN

- [ ] Replace `_git_tracked_files` with:

```python
def _git_scannable_files(root: Path) -> list[Path] | None:
    """List tracked and untracked non-ignored files in a Git repository.

    Args:
        root: Candidate repository root.

    Returns:
        Scannable file paths, or `None` when Git discovery is unavailable.
    """
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    files: list[Path] = []
    for raw in result.stdout.split(b"\x00"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8", errors="ignore"))
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        path = root / relative
        if path.is_file():
            files.append(path)
    return sorted(files)
```

- [ ] Replace contiguous test tokens with runtime construction:

```python
_SYNTHETIC_OPENAI_KEY = "sk-" + "livesecret1234567890"
```

Use that constant in all three tracing tests. This keeps the redaction behavior under test while removing committed scanner findings.

- [ ] Mount the entire repository read-only for container scanning:

```make
run_secret_scanning:
	$(COMPOSE) run --rm -v "$(CURDIR):/repo:ro" backend \
		python scripts/run_secret_scanning.py /repo
```

Apply the same `/repo` mount and path inside `container-check`.

- [ ] Implement exception validation. Require only the top-level `vulnerabilities` and `licenses` lists. Every entry requires:

  - non-empty `id`;
  - a statement beginning with `approved-by=`, followed by a non-empty identity,
    then `; reason=` and a non-empty rationale;
  - `expires_at` not earlier than the validation date;
  - no duplicate `(category, id)`.

- [ ] Create the initial fail-closed ignore file:

```yaml
vulnerabilities: []
licenses: []
```

Do not fabricate an exception to make the scan pass.

- [ ] Implement the CLI wrapper:

```python
def main(argv: Sequence[str] | None = None) -> int:
    """Validate Trivy exception metadata and expiration."""
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=".trivyignore.yaml")
    args = parser.parse_args(argv)
    try:
        exceptions = validate_trivy_exceptions(Path(args.path))
    except SecurityExceptionError as exc:
        print(f"security exception policy invalid: {exc}", file=sys.stderr)
        return 1
    print(f"security exceptions valid: {len(exceptions)}")
    return 0
```

- [ ] Change the Trivy CI step to:

```yaml
- name: Validate expiring security exceptions
  run: python scripts/validate_security_exceptions.py .trivyignore.yaml

- name: Run HIGH/CRITICAL vulnerability and license scan
  uses: aquasecurity/trivy-action@a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8
  with:
    scan-type: fs
    scan-ref: .
    scanners: vuln,license
    severity: HIGH,CRITICAL
    exit-code: "1"
    ignore-unfixed: false
    trivyignores: .trivyignore.yaml
    timeout: 3m
```

- [ ] Make `security-scan` depend on both repository secret scanning and exception validation. The actual Trivy binary gate remains authoritative in CI.

- [ ] Run:

```bash
source .venv/bin/activate && python -m pytest \
  backend/tests/unit/security/test_secrets.py \
  backend/tests/unit/security/test_security_exceptions.py \
  backend/tests/unit/security/test_ci_security_policy.py -q
source .venv/bin/activate && python scripts/run_secret_scanning.py .
source .venv/bin/activate && python scripts/validate_security_exceptions.py \
  .trivyignore.yaml
```

Expected: tests pass, secret scanning reports zero findings, and exception validation reports zero valid exceptions.

The epic PR’s `security-baseline` job must also pass Trivy. If it reports a current HIGH/CRITICAL finding, update the affected direct dependency to the lowest compatible patched version. If no patch exists, stop for explicit security approval before adding a dated exception.

- [ ] Commit:

```bash
git add backend/security scripts/validate_security_exceptions.py \
  backend/tests/unit/security \
  backend/tests/unit/observability/test_model_tracing.py \
  .trivyignore.yaml Makefile .github/workflows/ci-backend.yml
git commit -m "ci(e11): gate secrets vulnerabilities and licenses"
```

---

## Task 4: Redact credential-bearing settings and remove production default credentials

**Files:**

- Modify: `backend/config/settings.py`
- Modify: `backend/api/routers/features.py`
- Modify: `infrastructure/docker-compose.yml`
- Modify: `.env.example`
- Modify: `backend/tests/unit/config/test_settings.py`
- Modify: `backend/tests/unit/config/test_config_api.py`
- Modify: `backend/tests/integration/test_e0_s6_infrastructure.py`

### RED

- [ ] Add settings tests proving that:

  - `database_url` containing a password is returned as `"***"`;
  - `autodev_redis_url` containing a password is returned as `"***"`;
  - `autodev_minio_access_key` and secret key are `"***"`;
  - credential-free SQLite/Redis URLs remain usable;
  - production rejects an empty PostgreSQL password;
  - production rejects the known defaults `autodev`, `minioadmin`, `password`, `changeme`, and `change-me`.

```python
def test_redacted_dump_masks_credential_bearing_urls() -> None:
    settings = Settings(
        autodev_profile="prod",
        database_url="postgresql://svc:db-secret@postgres:5432/autodev",
        autodev_job_backend="redis",
        autodev_event_bus="redis",
        autodev_redis_url="redis://:redis-secret@redis:6379/0",
        storage_backend="s3",
        autodev_minio_endpoint="minio:9000",
        autodev_minio_access_key="service-access-key",
        autodev_minio_secret_key="service-secret-key",
    )

    redacted = settings.redacted_model_dump()

    assert redacted["database_url"] == "***"
    assert redacted["autodev_redis_url"] == "***"
    assert redacted["autodev_minio_access_key"] == "***"
    assert redacted["autodev_minio_secret_key"] == "***"
    assert "db-secret" not in repr(redacted)
    assert "redis-secret" not in repr(redacted)
```

- [ ] Strengthen the `/config` test so both the structured response and instruction examples omit the submitted API key:

```python
assert response.json()["config"]["llm"]["api_key"] == "***"
assert "test-key" not in response.text
```

- [ ] Add a Compose contract test asserting the rendered source contains no production fallback value for PostgreSQL or MinIO credentials.

- [ ] Run:

```bash
source .venv/bin/activate && python -m pytest \
  backend/tests/unit/config/test_settings.py \
  backend/tests/unit/config/test_config_api.py \
  backend/tests/integration/test_e0_s6_infrastructure.py -q
```

Expected: failures because credential-bearing URLs and the MinIO access key are exposed, known defaults are accepted, and Compose contains hardcoded defaults.

### GREEN

- [ ] Add:

```python
_SECRET_FIELDS = {
    "openai_api_key",
    "autodev_api_token",
    "autodev_minio_access_key",
    "autodev_minio_secret_key",
}

_CREDENTIAL_URL_FIELDS = {
    "database_url",
    "autodev_redis_url",
}

_KNOWN_INSECURE_DEFAULT_CREDENTIALS = frozenset(
    {"autodev", "minioadmin", "password", "changeme", "change-me"}
)
```

- [ ] Redact any configured URL containing a password:

```python
def _contains_url_password(value: str) -> bool:
    """Return whether a URL contains embedded password material."""
    try:
        return urlparse(value).password is not None
    except ValueError:
        return True


def redacted_model_dump(self) -> dict[str, Any]:
    """Dump settings with secret and credential-bearing values masked."""
    data = self.model_dump()
    for key in _SECRET_FIELDS:
        if data.get(key):
            data[key] = "***"
    for key in _CREDENTIAL_URL_FIELDS:
        value = data.get(key)
        if isinstance(value, str) and value and _contains_url_password(value):
            data[key] = "***"
    return data
```

- [ ] Extend production validation:

```python
database = urlparse(self.database_url)
database_password = database.password or ""
if not database_password:
    errors.append("prod profile requires a PostgreSQL password")
elif database_password.casefold() in _KNOWN_INSECURE_DEFAULT_CREDENTIALS:
    errors.append("prod profile rejects known default PostgreSQL credentials")

for field_name, value in (
    ("AUTODEV_MINIO_ACCESS_KEY", self.autodev_minio_access_key),
    ("AUTODEV_MINIO_SECRET_KEY", self.autodev_minio_secret_key),
):
    if value.casefold() in _KNOWN_INSECURE_DEFAULT_CREDENTIALS:
        errors.append(f"prod profile rejects known default {field_name}")
```

- [ ] Remove `_REDACTED` and its second masking loop from `features.py`; `Settings.redacted_model_dump()` becomes the only feature-settings redaction policy.

- [ ] Remove Compose credentials without breaking local Compose parsing:

```yaml
DATABASE_URL: "postgresql://autodev:${AUTODEV_POSTGRES_PASSWORD:-}@postgres:5432/autodev"
AUTODEV_MINIO_ACCESS_KEY: "${AUTODEV_MINIO_ACCESS_KEY:-}"
AUTODEV_MINIO_SECRET_KEY: "${AUTODEV_MINIO_SECRET_KEY:-}"
```

```yaml
POSTGRES_PASSWORD: "${AUTODEV_POSTGRES_PASSWORD:-}"
```

```yaml
MINIO_ROOT_USER: "${AUTODEV_MINIO_ACCESS_KEY:-}"
MINIO_ROOT_PASSWORD: "${AUTODEV_MINIO_SECRET_KEY:-}"
```

Missing credentials therefore produce empty values: the production `Settings` validator and the upstream PostgreSQL/MinIO containers fail closed, while `docker compose config` remains usable for local profiles.

- [ ] Add empty, documented production variables to `.env.example`; do not provide sample passwords:

```dotenv
AUTODEV_POSTGRES_PASSWORD=
AUTODEV_MINIO_ACCESS_KEY=
AUTODEV_MINIO_SECRET_KEY=
```

- [ ] Replace known-default values in positive production tests with unique test-only credentials.

- [ ] Run the same targeted tests plus:

```bash
docker compose -f infrastructure/docker-compose.yml config -q
```

Expected: all tests pass and Compose reports valid configuration.

- [ ] Commit:

```bash
git add backend/config/settings.py backend/api/routers/features.py \
  backend/tests/unit/config backend/tests/integration/test_e0_s6_infrastructure.py \
  infrastructure/docker-compose.yml .env.example
git commit -m "fix(e11): redact credentials and remove production defaults"
```

---

## Task 5: Make configured backups fail closed and expose durable backup health through E11-S1

**Files:**

- Modify: `backend/config/settings.py`
- Modify: `backend/persistence/backup.py`
- Create: `backend/persistence/backup_status.py`
- Create: `backend/observability/backup_metrics.py`
- Modify: `backend/api/main.py`
- Modify: `infrastructure/docker-compose.yml`
- Modify: `backend/tests/unit/persistence/test_backup.py`
- Modify: `backend/tests/unit/persistence/test_backup_restore.py`
- Create: `backend/tests/unit/persistence/test_backup_status.py`
- Create: `backend/tests/unit/observability/test_backup_metrics.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class BackupStatus:
    last_attempt_timestamp: float
    last_success_timestamp: float | None
    consecutive_failures: int
    last_result: Literal["success", "failure"]
```

```python
class BackupStatusStore:
    def __init__(self, path: Path) -> None:
        """Initialize a durable, local backup-status store."""

    def read(self) -> BackupStatus | None:
        """Read the latest backup status."""

    def record(
        self,
        *,
        success: bool,
        occurred_at: datetime | None = None,
    ) -> BackupStatus:
        """Atomically record a sanitized backup outcome."""
```

```python
def register_backup_observables(
    *,
    meter: Meter,
    status_store: BackupStatusStore,
) -> None:
    """Register backup health gauges with the E11-S1 meter."""
```

### RED

- [ ] Replace the two tests that currently expect missing `pg_dump`/`pg_restore` to be skipped:

```python
def test_backup_postgres_fails_when_pg_dump_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    manager = BackupManager(
        database_url="postgresql://svc:db-secret@postgres/autodev"
    )

    with pytest.raises(
        BackupError,
        match="PostgreSQL backup is configured but pg_dump is not available",
    ):
        manager._backup_postgres(tmp_path, {"components": {}})
```

Add the equivalent `pg_restore` test for a completed PostgreSQL manifest entry.

- [ ] Add a test proving the PostgreSQL password is absent from subprocess arguments and error output while `PGPASSWORD` is passed through the subprocess environment.

- [ ] Add status-store tests for:

  - no status file;
  - first success;
  - failure preserving the previous success timestamp;
  - consecutive failures;
  - success resetting failures;
  - mode `0600`;
  - valid atomic JSON after repeated writes;
  - no exception text or secret material persisted.

- [ ] Add a CLI test proving a failed configured backup records failure and returns `1`.

- [ ] Add an OpenTelemetry test with `InMemoryMetricReader` proving these gauges:

  - `autodev_backup_last_attempt_timestamp_seconds`;
  - `autodev_backup_last_success_timestamp_seconds`;
  - `autodev_backup_consecutive_failures`;
  - `autodev_backup_last_result`.

- [ ] Run:

```bash
source .venv/bin/activate && python -m pytest \
  backend/tests/unit/persistence/test_backup.py \
  backend/tests/unit/persistence/test_backup_restore.py \
  backend/tests/unit/persistence/test_backup_status.py \
  backend/tests/unit/observability/test_backup_metrics.py -q
```

Expected: failures because missing PostgreSQL tools are skipped, status persistence does not exist, and no S1-backed metrics are registered.

### GREEN

- [ ] Resolve and use the exact executable returned by `shutil.which`. Raise `BackupError` when the configured component’s tool is absent.

- [ ] Strip the password from the connection URL passed on the command line and use `PGPASSWORD`:

```python
def _postgres_cli_connection(
    database_url: str,
) -> tuple[str, dict[str, str]]:
    """Build a password-free PostgreSQL URL and subprocess environment."""
    parsed = urlsplit(database_url)
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    username = quote(unquote(parsed.username or ""), safe="")
    credentials = f"{username}@" if username else ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    safe_url = urlunsplit(
        (
            parsed.scheme,
            f"{credentials}{host}{port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )
    environment = os.environ.copy()
    if parsed.password is not None:
        environment["PGPASSWORD"] = unquote(parsed.password)
    return safe_url, environment
```

Use the sanitized URL for both `pg_dump` and `pg_restore`. Never include the original URL in errors.

- [ ] Update PostgreSQL backup documentation strings: a non-PostgreSQL deployment is skipped; a configured PostgreSQL deployment missing required tooling fails.

- [ ] Add `autodev_backup_status_path: str = ".autodev/backup-status.json"` and set `/data/backup-status.json` for container services.

- [ ] Implement atomic status writes with owner-only permissions:

```python
def _write(self, status: BackupStatus) -> None:
    self._path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=self._path.parent,
        prefix=f".{self._path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(asdict(status), handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, self._path)
        os.chmod(self._path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
```

Persist only timestamps, count, and result—never an exception message.

- [ ] Record backup success only after the manifest and all configured components complete. On any `BackupError` or `OSError`, record failure before returning `1`. Failure to write status also returns `1`.

- [ ] Register gauges through S1’s meter:

```python
def register_backup_observables(
    *,
    meter: Meter,
    status_store: BackupStatusStore,
) -> None:
    """Register observable backup-health gauges.

    Args:
        meter: Meter supplied by E11-S1.
        status_store: Durable source of sanitized backup state.
    """
    def value(
        field: str,
    ) -> Callable[[CallbackOptions], Iterable[Observation]]:
        def observe(_: CallbackOptions) -> Iterable[Observation]:
            status = status_store.read()
            if status is None:
                return ()
            observed = getattr(status, field)
            if observed is None:
                return ()
            if field == "last_result":
                observed = 1 if observed == "success" else 0
            return (Observation(float(observed)),)

        return observe

    meter.create_observable_gauge(
        "autodev_backup_last_attempt_timestamp_seconds",
        callbacks=[value("last_attempt_timestamp")],
        description="Unix timestamp of the latest backup attempt",
        unit="s",
    )
    meter.create_observable_gauge(
        "autodev_backup_last_success_timestamp_seconds",
        callbacks=[value("last_success_timestamp")],
        description="Unix timestamp of the latest successful backup",
        unit="s",
    )
    meter.create_observable_gauge(
        "autodev_backup_consecutive_failures",
        callbacks=[value("consecutive_failures")],
        description="Number of consecutive failed backup attempts",
    )
    meter.create_observable_gauge(
        "autodev_backup_last_result",
        callbacks=[value("last_result")],
        description="Latest backup result, one for success and zero for failure",
    )
```

- [ ] Register once during application observability startup, after S1 installs the meter provider:

```python
register_backup_observables(
    meter=get_meter("backend.persistence.backup"),
    status_store=BackupStatusStore(
        Path(settings.autodev_backup_status_path)
    ),
)
```

Do not add a parallel registry or `/metrics` renderer.

- [ ] Run the targeted backup/metrics tests.

Expected: all pass; subprocess assertions contain no database password.

- [ ] Commit:

```bash
git add backend/config/settings.py backend/persistence \
  backend/observability/backup_metrics.py backend/api/main.py \
  backend/tests/unit/persistence backend/tests/unit/observability/test_backup_metrics.py \
  infrastructure/docker-compose.yml
git commit -m "fix(e11): fail closed and observe configured backups"
```

---

## Task 6: Configure actionable alerts, publish executable runbooks, and close the story

**Files:**

- Modify: `infrastructure/docker-compose.yml`
- Modify: `infrastructure/observability/prometheus.yaml`
- Modify: `infrastructure/observability/prometheus-rules.yml`
- Create: `infrastructure/observability/alertmanager.yml`
- Create: `backend/tests/unit/observability/test_security_alert_assets.py`
- Create: `docs/v2_platform/runbooks/e11_incident_response.md`
- Modify: `docs/v2_platform/runbooks/e8_restore_runbook.md`
- Modify: `docs/ops/observability.md`
- Modify: `docs/ops/backup_restore.md`
- Modify: `docs/security.md`
- Modify: `docs/security/baseline.md`
- Modify: `docs/config.md`
- Modify: `docs/implementation/patches_and_validation.md`
- Modify: `docs/v2_platform/phases/e11_observability_security_multitenant.md`
- Modify: `docs/v2_platform/progress.md`
- Modify: `CHANGELOG.md`

### RED

- [ ] Add an asset contract test that loads the Prometheus and Alertmanager YAML and asserts:

  - Prometheus targets `alertmanager:9093`;
  - all three backup alerts exist;
  - every alert has `severity`, `service`, `summary`, `description`, and HTTPS `runbook_url`;
  - stale backup threshold is 300 seconds;
  - a single consecutive failure becomes alertable;
  - Alertmanager has a default route and receiver;
  - Compose places Alertmanager under the `observability` profile.

```python
def test_backup_alerts_are_actionable() -> None:
    rules = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    alerts = {
        rule["alert"]: rule
        for group in rules["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }

    assert {
        "AutoDevBackupNeverSucceeded",
        "AutoDevBackupStale",
        "AutoDevBackupFailing",
    } <= alerts.keys()

    for alert in alerts.values():
        assert alert["labels"]["severity"] in {"warning", "critical"}
        assert alert["labels"]["service"] == "backup"
        assert alert["annotations"]["summary"]
        assert alert["annotations"]["description"]
        assert alert["annotations"]["runbook_url"].startswith("https://")

    assert "> 300" in alerts["AutoDevBackupStale"]["expr"]
    assert "> 0" in alerts["AutoDevBackupFailing"]["expr"]
```

- [ ] Run:

```bash
source .venv/bin/activate && python -m pytest \
  backend/tests/unit/observability/test_security_alert_assets.py -q
```

Expected: failure because the alerts and Alertmanager assets do not exist.

### GREEN

- [ ] Append this group to the S1 rules file:

```yaml
- name: autodev-e11-s4-backup
  rules:
    - alert: AutoDevBackupNeverSucceeded
      expr: absent(autodev_backup_last_success_timestamp_seconds)
      for: 5m
      labels:
        severity: critical
        service: backup
      annotations:
        summary: AutoDev has no successful backup metric
        description: No successful backup was observed during the five-minute RPO window.
        runbook_url: https://github.com/acpguedes/autodev/blob/main/docs/v2_platform/runbooks/e11_incident_response.md#backup-never-succeeded

    - alert: AutoDevBackupStale
      expr: time() - autodev_backup_last_success_timestamp_seconds > 300
      for: 1m
      labels:
        severity: critical
        service: backup
      annotations:
        summary: AutoDev backup is older than the RPO
        description: The latest successful backup is more than five minutes old.
        runbook_url: https://github.com/acpguedes/autodev/blob/main/docs/v2_platform/runbooks/e11_incident_response.md#backup-stale

    - alert: AutoDevBackupFailing
      expr: autodev_backup_consecutive_failures > 0
      for: 1m
      labels:
        severity: warning
        service: backup
      annotations:
        summary: AutoDev backup attempt failed
        description: One or more consecutive backup attempts failed; inspect tooling and storage immediately.
        runbook_url: https://github.com/acpguedes/autodev/blob/main/docs/v2_platform/runbooks/e11_incident_response.md#backup-failing
```

- [ ] Wire Prometheus to Alertmanager in `infrastructure/observability/prometheus.yaml`:

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093
```

- [ ] Add a local-first Alertmanager configuration:

```yaml
global:
  resolve_timeout: 5m

route:
  receiver: operator-ui
  group_by:
    - alertname
    - service
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: operator-ui
```

This retains and groups alerts in the OSS Alertmanager UI. The observability runbook must explain how operators replace or mount this receiver with their SMTP/webhook integration; do not hardcode external credentials.

- [ ] Add the Alertmanager service to the existing `observability` profile, exposing port `9093`, mounting the config read-only, enabling `no-new-privileges`, and using a named data volume for silences. Pin the image to the current production release `prom/alertmanager:v0.32.1`. Do not create a second observability profile.

- [ ] Write `e11_incident_response.md` with executable sections:

  1. alert-to-severity and owner table;
  2. first five minutes: `/health`, Prometheus target status, `/metrics`, Compose service status, and sanitized logs;
  3. `BackupNeverSucceeded`, `BackupStale`, and `BackupFailing` procedures;
  4. sandbox containment by disabling `AUTODEV_ENABLE_SANDBOX` and restarting the backend;
  5. plugin containment through `POST /v2/extensions/plugin/{plugin_id}/disable`;
  6. evidence preservation without copying secret values;
  7. E8 restore invocation and integrity verification;
  8. recovery criteria, communication, and incident closure;
  9. quarterly network-denial and restore drills;
  10. escalation when the five-minute RPO or thirty-minute RTO is missed.

- [ ] Correct `e8_restore_runbook.md` references from the nonexistent `backend/tests/test_backup_restore.py` to:

```text
backend/tests/unit/persistence/test_backup_restore.py
```

Document that configured PostgreSQL backup/restore tooling now fails closed.

- [ ] Update:

  - `docs/ops/observability.md`: Collector, Prometheus, Alertmanager, ports, alert routing, receiver override, and validation commands.
  - `docs/ops/backup_restore.md`: no example passwords, five-minute scheduling requirement, status path, alerts, and restore drill.
  - `docs/security.md`: ADR-020 trust boundary, typed sandbox, scanner policy, exceptions, credential redaction, and residual E13/E32/E33 risks.
  - `docs/security/baseline.md`: zero secret baseline and HIGH/CRITICAL vulnerability/license policy.
  - `docs/config.md`: sandbox timeout, trusted plugin IDs, backup status path, and required production credentials.
  - `docs/implementation/patches_and_validation.md`: read-only workspace mount, network default, local fallback warning, and mandatory security contract.
  - `CHANGELOG.md`: E11-S4 behavior and production compatibility note.

- [ ] Update only E11-S4 to complete in the phase and progress trackers. Recalculate the epic aggregate from the actual rebased state; do not mark E11-S1–S3 complete unless their evidence has landed.

- [ ] Refresh the graph before committing:

```bash
graphify update .
```

Expected: graph update succeeds and only reflects the story changes.

### Alert and story verification

- [ ] Validate YAML and rule loading:

```bash
docker compose -f infrastructure/docker-compose.yml \
  --profile observability config -q
docker compose -f infrastructure/docker-compose.yml \
  --profile observability run --rm \
  --entrypoint /bin/promtool prometheus \
  check rules /etc/prometheus/prometheus-rules.yml
docker compose -f infrastructure/docker-compose.yml \
  --profile observability run --rm \
  --entrypoint /bin/amtool alertmanager \
  check-config /etc/alertmanager/alertmanager.yml
```

Expected: Compose, Prometheus rules, and Alertmanager configuration all report success.

- [ ] Run the consolidated story-scoped tests once:

```bash
source .venv/bin/activate && python -m pytest \
  backend/tests/unit/plugins/test_plugins_host.py \
  backend/tests/unit/plugins/test_plugins_permissions.py \
  backend/tests/unit/plugins/test_plugins_manifest.py \
  backend/tests/unit/validation/test_sandbox_runner.py \
  backend/tests/unit/validation/test_validation_api.py \
  backend/tests/integration/test_sandbox_security_contract.py \
  backend/tests/unit/security \
  backend/tests/unit/config/test_settings.py \
  backend/tests/unit/config/test_config_api.py \
  backend/tests/unit/persistence/test_backup.py \
  backend/tests/unit/persistence/test_backup_restore.py \
  backend/tests/unit/persistence/test_backup_status.py \
  backend/tests/unit/observability/test_backup_metrics.py \
  backend/tests/unit/observability/test_security_alert_assets.py \
  backend/tests/integration/test_e0_s6_infrastructure.py -q -rs
```

Expected: all pass; the Docker security contract reports no skips.

- [ ] Run static and security checks once:

```bash
source .venv/bin/activate && python -m ruff check \
  backend/config backend/plugins backend/validation backend/security \
  backend/persistence backend/observability backend/api \
  backend/tests/unit/plugins backend/tests/unit/validation \
  backend/tests/unit/security backend/tests/unit/config \
  backend/tests/unit/persistence backend/tests/unit/observability
source .venv/bin/activate && python -m mypy backend
source .venv/bin/activate && python scripts/run_secret_scanning.py .
source .venv/bin/activate && python scripts/validate_security_exceptions.py \
  .trivyignore.yaml
git diff --check
```

Expected: zero lint/type errors, zero secret findings, valid unexpired exceptions, and no whitespace errors.

- [ ] Commit:

```bash
git add infrastructure docs CHANGELOG.md graphify-out \
  backend/tests/unit/observability/test_security_alert_assets.py
git commit -m "docs(e11): publish execution security alerts and runbooks"
```

- [ ] Merge the completed story into the E11 epic branch, push it, and delete the story branch. Do not open the epic-to-`main` PR until all E11 stories are complete and `make check` is green.

## Self-Review Completed

- [x] Six cohesive implementation tasks; no micro-task fragmentation.
- [x] E11-S4-T1 maps to ADR-020, production plugin rejection, and the Docker security contract.
- [x] E11-S4-T2 maps to redaction, removal of defaults, repository-wide secret scanning, and HIGH/CRITICAL vulnerability/license gates.
- [x] E11-S4-T3 maps to fail-closed backup status, S1 metrics, Prometheus rules, Alertmanager, and executable runbooks.
- [x] Real network denial is proven inside Docker; filesystem, privilege, resource, timeout, and mount controls have contract coverage.
- [x] In-process plugin policy preserves the current manifest contract.
- [x] Backup observability reuses E11-S1 `get_meter`, `prometheus.yaml`, and the shared `prometheus-rules.yml` file.
- [x] No E32 execution abstraction or E33 secret store is introduced.
- [x] Every code task begins with a concrete failing test and names its expected failure.
- [x] Every task has exact files, interfaces, verification commands, expected outcomes, and a focused commit.
- [x] Dynamic security findings cannot be waived without explicit, expiring approval.
- [x] Full-suite execution remains correctly reserved for the epic-to-`main` PR.
