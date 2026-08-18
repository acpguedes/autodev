"""Structured CLI for local AutoDev Architect operations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Sequence

from backend.config import RuntimeConfigService
from backend.config.settings import get_settings, reset_settings_cache
from backend.llm.factory import get_chat_model
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import reset_store_cache
from backend.repository import RepositoryIntelligenceService

if TYPE_CHECKING:
    from backend.quotas.contracts import TenantQuotaPolicy


def build_parser() -> argparse.ArgumentParser:
    """Build the ``autodev`` CLI argument parser with all subcommands.

    Returns:
        The configured top-level argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="autodev",
        description="CLI estruturada para configurar e operar o AutoDev Architect localmente.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version, commit, and build-date metadata and exit (E34-S1).",
    )
    parser.add_argument(
        "--shell",
        action="store_true",
        help="Start the governed interactive shell (E14-S6), talking only to the Control Plane API.",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "approval", "hybrid"),
        default="auto",
        help="Execution mode for --shell (E14-S3): auto (default), approval, or hybrid.",
    )
    parser.add_argument(
        "--command",
        dest="shell_command",
        default=None,
        help="With --shell: run one goal non-interactively and exit.",
    )
    parser.add_argument(
        "--base-url",
        dest="shell_base_url",
        default=None,
        help="With --shell: Control Plane API base URL (default: http://127.0.0.1:8000, or AUTODEV_SHELL_BASE_URL).",
    )
    # required=False (not the historical default) so `autodev --shell` needs
    # no subcommand; main() still enforces a command when --shell is absent,
    # preserving the prior "a subcommand is required" behavior exactly.
    subparsers = parser.add_subparsers(dest="command", required=False)

    config_parser = subparsers.add_parser("config", help="Exibir ou atualizar a configuração runtime")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)

    config_show_parser = config_subparsers.add_parser("show", help="Renderiza a configuração atual")
    config_show_parser.add_argument(
        "--format",
        choices=("json", "env"),
        default="json",
        help="Formato de saída estruturada.",
    )
    config_show_parser.set_defaults(handler=_handle_config_show)

    config_set_parser = config_subparsers.add_parser("set", help="Atualiza campos da configuração")
    config_set_parser.add_argument("--provider")
    config_set_parser.add_argument("--model")
    config_set_parser.add_argument("--base-url")
    config_set_parser.add_argument("--temperature", type=float)
    config_set_parser.add_argument("--api-key")
    config_set_parser.add_argument("--project-root")
    config_set_parser.add_argument("--repository-label")
    config_set_parser.add_argument("--default-goal")
    config_set_parser.set_defaults(handler=_handle_config_set)

    config_validate_parser = config_subparsers.add_parser(
        "validate",
        help="Valida a configuração declarativa ativa.",
    )
    config_validate_parser.add_argument("--profile", choices=("local", "prod"))
    config_validate_parser.add_argument("--settings-file")
    config_validate_parser.set_defaults(handler=_handle_config_validate)

    quotas_parser = subparsers.add_parser("quotas", help="Gerencia políticas de quota por tenant (E11-S3)")
    quotas_subparsers = quotas_parser.add_subparsers(dest="quotas_command", required=True)

    quotas_get_parser = quotas_subparsers.add_parser(
        "get", help="Exibe a política efetiva e o uso corrente de um tenant"
    )
    quotas_get_parser.add_argument("tenant_id")
    quotas_get_parser.set_defaults(handler=_handle_quotas_get)

    quotas_set_parser = quotas_subparsers.add_parser(
        "set", help="Define (ou substitui) a política de quota durável de um tenant"
    )
    quotas_set_parser.add_argument("tenant_id")
    quotas_set_parser.add_argument("--max-concurrent-runs", type=int, required=True)
    quotas_set_parser.add_argument("--max-storage-bytes", type=int, required=True)
    quotas_set_parser.add_argument("--monthly-token-limit", type=int, required=True)
    quotas_set_parser.add_argument("--monthly-cost-microusd", type=int, required=True)
    quotas_set_parser.add_argument("--requests-per-second", type=int, required=True)
    quotas_set_parser.add_argument("--max-run-tokens", type=int, default=None)
    quotas_set_parser.add_argument("--max-run-cost-microusd", type=int, default=None)
    quotas_set_parser.add_argument("--max-run-wall-clock-ms", type=int, default=None)
    quotas_set_parser.add_argument("--max-run-steps", type=int, default=None)
    quotas_set_parser.add_argument(
        "--expected-version",
        type=int,
        default=None,
        help="Versão esperada para escrita otimista; omitido substitui incondicionalmente.",
    )
    quotas_set_parser.set_defaults(handler=_handle_quotas_set)

    secrets_parser = subparsers.add_parser(
        "secrets", help="Gerencia segredos com referência escopada por tenant (E33-S1)"
    )
    secrets_subparsers = secrets_parser.add_subparsers(dest="secrets_command", required=True)

    secrets_create_parser = secrets_subparsers.add_parser(
        "create", help="Cria a primeira versão de um segredo"
    )
    secrets_create_parser.add_argument("tenant_id")
    secrets_create_parser.add_argument("name")
    secrets_create_parser.add_argument("--project", default="default")
    secrets_create_parser.add_argument(
        "--value-stdin",
        action="store_true",
        required=True,
        help="Lê o valor bruto da stdin (nunca como argumento de linha de comando).",
    )
    secrets_create_parser.set_defaults(handler=_handle_secrets_create)

    secrets_rotate_parser = secrets_subparsers.add_parser(
        "rotate", help="Armazena uma nova versão de um segredo existente"
    )
    secrets_rotate_parser.add_argument("tenant_id")
    secrets_rotate_parser.add_argument("name")
    secrets_rotate_parser.add_argument("--project", default="default")
    secrets_rotate_parser.add_argument(
        "--value-stdin",
        action="store_true",
        required=True,
        help="Lê o novo valor bruto da stdin (nunca como argumento de linha de comando).",
    )
    secrets_rotate_parser.set_defaults(handler=_handle_secrets_rotate)

    secrets_revoke_parser = secrets_subparsers.add_parser(
        "revoke", help="Revoga um segredo (falha fechada em resoluções futuras)"
    )
    secrets_revoke_parser.add_argument("tenant_id")
    secrets_revoke_parser.add_argument("name")
    secrets_revoke_parser.add_argument("--project", default="default")
    secrets_revoke_parser.set_defaults(handler=_handle_secrets_revoke)

    secrets_list_parser = secrets_subparsers.add_parser(
        "list", help="Lista metadados dos segredos de um tenant (nunca valores)"
    )
    secrets_list_parser.add_argument("tenant_id")
    secrets_list_parser.add_argument("--project", default=None)
    secrets_list_parser.set_defaults(handler=_handle_secrets_list)

    sessions_parser = subparsers.add_parser("sessions", help="Operações de sessão")
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command", required=True)
    sessions_list_parser = sessions_subparsers.add_parser("list", help="Lista sessões persistidas")
    sessions_list_parser.set_defaults(handler=_handle_sessions_list)

    plan_parser = subparsers.add_parser("plan", help="Cria uma nova sessão de planejamento")
    plan_parser.add_argument("goal", help="Objetivo principal da sessão")
    plan_parser.set_defaults(handler=_handle_plan_create)

    run_parser = subparsers.add_parser("run", help="Envia mensagens ou executa o plano derivado")
    run_subparsers = run_parser.add_subparsers(dest="run_command", required=True)

    run_message_parser = run_subparsers.add_parser("message", help="Executa um ciclo completo de agentes")
    run_message_parser.add_argument("session_id")
    run_message_parser.add_argument("message")
    run_message_parser.set_defaults(handler=_handle_run_message)

    run_execute_parser = run_subparsers.add_parser("execute-plan", help="Executa o backlog derivado")
    run_execute_parser.add_argument("session_id")
    run_execute_parser.set_defaults(handler=_handle_execute_plan)

    repository_parser = subparsers.add_parser("repository", help="Contexto estruturado do repositório")
    repository_subparsers = repository_parser.add_subparsers(dest="repository_command", required=True)
    repository_context_parser = repository_subparsers.add_parser(
        "context",
        help="Retorna o contexto ranqueado do repositório ativo",
    )
    repository_context_parser.add_argument("--query", default="", help="Consulta lexical inicial")
    repository_context_parser.add_argument("--limit", type=int, default=6)
    repository_context_parser.set_defaults(handler=_handle_repository_context)

    artifacts_cleanup_parser = subparsers.add_parser(
        "artifacts-cleanup",
        help="Remove objetos de artefatos sem ponteiro registrado no State Store",
    )
    artifacts_cleanup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas reporta o que seria removido, sem apagar nada",
    )
    artifacts_cleanup_parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help=(
            "Idade mínima (dias) de um objeto sem referência antes da remoção; "
            "padrão AUTODEV_ARTIFACT_RETENTION_DAYS, -1 desativa a coleta"
        ),
    )
    artifacts_cleanup_parser.set_defaults(handler=_handle_artifacts_cleanup)

    sdk_parser = subparsers.add_parser("sdk", help="Ferramentas do SDK de plugins")
    sdk_subparsers = sdk_parser.add_subparsers(dest="sdk_command", required=True)
    sdk_new_parser = sdk_subparsers.add_parser("new", help="Cria projetos do SDK")
    sdk_new_subparsers = sdk_new_parser.add_subparsers(dest="sdk_new_kind", required=True)
    sdk_plugin_parser = sdk_new_subparsers.add_parser("plugin", help="Cria um plugin")
    sdk_plugin_parser.add_argument("plugin_id")
    sdk_plugin_parser.add_argument("--output", required=True)
    sdk_plugin_parser.set_defaults(handler=_handle_sdk_new_plugin)

    permissions_parser = subparsers.add_parser(
        "permissions", help="Manage execution dynamic permissions (E14-S3/S7)"
    )
    permissions_subparsers = permissions_parser.add_subparsers(dest="permissions_command", required=True)
    permissions_list_parser = permissions_subparsers.add_parser(
        "list", help="List granted dynamic permissions"
    )
    permissions_list_parser.add_argument("--base-url", default=None)
    permissions_list_parser.set_defaults(handler=_handle_permissions_list)
    permissions_revoke_parser = permissions_subparsers.add_parser(
        "revoke", help="Revoke a dynamic permission"
    )
    permissions_revoke_parser.add_argument("permission_id")
    permissions_revoke_parser.add_argument("--base-url", default=None)
    permissions_revoke_parser.set_defaults(handler=_handle_permissions_revoke)

    subparsers.add_parser(
        "doctor", help="Run preflight diagnostics (E34-S2)"
    ).set_defaults(handler=_handle_doctor)

    subparsers.add_parser(
        "bootstrap",
        help="Preflight-check and initialize the configured state store for self-host (E34-S2)",
    ).set_defaults(handler=_handle_bootstrap)

    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Back up, then migrate the configured state store, refusing an incompatible schema (E34-S3)",
    )
    upgrade_parser.add_argument(
        "--backup-dir",
        default=None,
        help="Directory for the pre-upgrade backup; default: .autodev/upgrade-backups/<timestamp>.",
    )
    upgrade_parser.add_argument(
        "--target-version",
        default=None,
        help="Version label to look up release notes for in CHANGELOG.md.",
    )
    upgrade_parser.set_defaults(handler=_handle_upgrade)

    try:
        from backend.cli_plugins import register_subcommands
        register_subcommands(subparsers)
    except Exception:
        pass

    return parser


def _configure_cli_observability() -> None:
    """Configure the observability runtime once, with JSON logs on stderr.

    ``configure_observability`` binds its structured JSON log handler to
    whichever stream is current ``sys.stdout`` when it runs, which is the
    right default for a long-lived service but not for a CLI: any WARNING
    or INFO log emitted while a command runs (agent fallback notices, for
    example) would otherwise interleave with the command's own JSON result
    on stdout and break the single-JSON-object-on-stdout contract every
    downstream machine-readable consumer relies on. Configuring eagerly
    here, with stdout swapped to stderr for just this call, binds that
    handler to stderr instead; any later lazy ``get_tracer()``/
    ``get_meter()`` call reuses this already-configured runtime rather than
    reconfiguring against whatever stream happens to be current then.
    """
    from backend.observability.runtime import get_observability_runtime

    previous_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        get_observability_runtime()
    finally:
        sys.stdout = previous_stdout


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the selected subcommand handler.

    Args:
        argv: Argument vector to parse; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code returned by the dispatched handler.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from backend.ops.version import get_version_info

        print(json.dumps(get_version_info().as_dict(), ensure_ascii=False))
        return 0

    # --command works standalone too (E14-S7): "autodev --command '<goal>'"
    # is the shell's one-shot round trip without entering the REPL, exactly
    # as "autodev --shell --command '<goal>'" already did.
    if args.shell or args.shell_command:
        from backend.cli_shell import main as shell_main

        shell_argv: list[str] = ["--mode", args.mode]
        if args.shell_command:
            shell_argv += ["--command", args.shell_command]
        if args.shell_base_url:
            shell_argv += ["--base-url", args.shell_base_url]
        return shell_main(shell_argv)

    _configure_cli_observability()
    if args.command is None:
        # No subcommand and no --shell/--command: the default experience
        # (E14-S7) is to start the web/local server and open the browser,
        # reusing E18's existing front door (GET / -> AUTODEV_UI_URL) rather
        # than building new bundling.
        return _handle_start_web(args)
    return int(args.handler(args))


def _build_runtime_services() -> tuple[RuntimeConfigService, OrchestratorService, RepositoryIntelligenceService]:
    """Build the runtime config, orchestrator, and repository services for a CLI invocation.

    Returns:
        A tuple of ``(config_service, orchestrator, repository_service)``.
    """
    config_service = RuntimeConfigService()
    runtime_config = config_service.apply_to_environment()
    get_chat_model.cache_clear()
    reset_store_cache()
    project_root = Path(runtime_config.repository.project_root)
    orchestrator = OrchestratorService(project_root=project_root)
    repository_service = RepositoryIntelligenceService(project_root=project_root)
    return config_service, orchestrator, repository_service


def _handle_config_show(args: argparse.Namespace) -> int:
    """Handle ``autodev config show``: print the active runtime configuration.

    Args:
        args: Parsed CLI arguments, including ``format``.

    Returns:
        Process exit code, always ``0``.
    """
    config_service, _, _ = _build_runtime_services()
    document = config_service.load_document()
    if args.format == "env":
        print(document.instructions.env_file_example)
        return 0

    print(
        json.dumps(
            {
                "config": document.config.model_dump(),
                "instructions": document.instructions.model_dump(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _policy_to_dict(policy: "TenantQuotaPolicy") -> dict:
    """Render a tenant quota policy as a plain, JSON-serializable dict."""
    from backend.quotas.contracts import policy_to_json

    payload = json.loads(policy_to_json(policy))
    payload["tenant_id"] = policy.tenant_id
    payload["version"] = policy.version
    return payload


def _handle_quotas_get(args: argparse.Namespace) -> int:
    """Handle ``autodev quotas get``: print a tenant's effective policy and usage.

    Args:
        args: Parsed CLI arguments, including ``tenant_id``.

    Returns:
        Process exit code, always ``0``.
    """
    from backend.quotas.service import QuotaService

    snapshot = QuotaService().get_usage(args.tenant_id)
    print(
        json.dumps(
            {
                "policy": _policy_to_dict(snapshot.policy),
                "usage": {
                    "concurrent_runs": snapshot.concurrent_runs,
                    "storage_bytes_used": snapshot.storage_bytes_used,
                    "monthly_tokens_used": snapshot.monthly_tokens_used,
                    "monthly_cost_microusd_used": snapshot.monthly_cost_microusd_used,
                    "month_window_key": snapshot.month_window_key,
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_quotas_set(args: argparse.Namespace) -> int:
    """Handle ``autodev quotas set``: durably store a tenant's quota policy.

    Args:
        args: Parsed CLI arguments with the policy fields and an optional
            ``expected_version`` for optimistic-concurrency control.

    Returns:
        Process exit code: ``0`` on success, ``1`` on a version conflict or
        an invalid (non-positive) limit.
    """
    from backend.quotas.contracts import RunBudgetLimits, TenantQuotaPolicy
    from backend.quotas.service import QuotaService

    try:
        policy = TenantQuotaPolicy(
            tenant_id=args.tenant_id,
            max_concurrent_runs=args.max_concurrent_runs,
            max_storage_bytes=args.max_storage_bytes,
            monthly_token_limit=args.monthly_token_limit,
            monthly_cost_microusd=args.monthly_cost_microusd,
            requests_per_second=args.requests_per_second,
            default_run_budget=RunBudgetLimits(
                max_tokens=args.max_run_tokens,
                max_cost_microusd=args.max_run_cost_microusd,
                max_wall_clock_ms=args.max_run_wall_clock_ms,
                max_steps=args.max_run_steps,
            ),
        )
        stored = QuotaService().set_policy(policy, expected_version=args.expected_version)
    except ValueError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "policy": _policy_to_dict(stored)}, indent=2, ensure_ascii=False))
    return 0


def _metadata_to_dict(metadata) -> dict:  # type: ignore[no-untyped-def]
    """Render a secret's metadata as a plain, JSON-serializable dict -- never a value."""
    return {
        "tenant_id": metadata.reference.tenant_id,
        "project": metadata.reference.project,
        "name": metadata.reference.name,
        "version": metadata.version,
        "status": metadata.status.value,
        "created_at": metadata.created_at,
        "rotated_at": metadata.rotated_at,
        "revoked_at": metadata.revoked_at,
    }


def _handle_secrets_create(args: argparse.Namespace) -> int:
    """Handle ``autodev secrets create``: create the first version of a secret.

    Args:
        args: Parsed CLI arguments, including ``tenant_id``/``name``/``project``.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the reference already exists.
    """
    from backend.secret_store.contracts import SecretReference
    from backend.secret_store.service import SecretService

    value = sys.stdin.readline().rstrip("\n")
    reference = SecretReference(tenant_id=args.tenant_id, project=args.project, name=args.name)
    try:
        metadata = SecretService().create(reference, value, actor_id="cli")
    except ValueError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "secret": _metadata_to_dict(metadata)}, indent=2, ensure_ascii=False))
    return 0


def _handle_secrets_rotate(args: argparse.Namespace) -> int:
    """Handle ``autodev secrets rotate``: store a new version of an existing secret.

    Args:
        args: Parsed CLI arguments, including ``tenant_id``/``name``/``project``.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the reference is unknown.
    """
    from backend.secret_store.contracts import SecretNotFoundError, SecretReference
    from backend.secret_store.service import SecretService

    value = sys.stdin.readline().rstrip("\n")
    reference = SecretReference(tenant_id=args.tenant_id, project=args.project, name=args.name)
    try:
        metadata = SecretService().rotate(reference, value, actor_id="cli")
    except SecretNotFoundError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "secret": _metadata_to_dict(metadata)}, indent=2, ensure_ascii=False))
    return 0


def _handle_secrets_revoke(args: argparse.Namespace) -> int:
    """Handle ``autodev secrets revoke``: revoke a secret, failing future resolution closed.

    Args:
        args: Parsed CLI arguments, including ``tenant_id``/``name``/``project``.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the reference is unknown.
    """
    from backend.secret_store.contracts import SecretNotFoundError, SecretReference
    from backend.secret_store.service import SecretService

    reference = SecretReference(tenant_id=args.tenant_id, project=args.project, name=args.name)
    try:
        metadata = SecretService().revoke(reference, actor_id="cli")
    except SecretNotFoundError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "secret": _metadata_to_dict(metadata)}, indent=2, ensure_ascii=False))
    return 0


def _handle_secrets_list(args: argparse.Namespace) -> int:
    """Handle ``autodev secrets list``: list a tenant's secrets' metadata.

    Args:
        args: Parsed CLI arguments, including ``tenant_id`` and optional ``project``.

    Returns:
        Process exit code, always ``0``.
    """
    from backend.secret_store.service import SecretService

    metadata_list = SecretService().list_metadata(args.tenant_id, project=args.project)
    print(
        json.dumps(
            {"secrets": [_metadata_to_dict(item) for item in metadata_list]},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_artifacts_cleanup(args: argparse.Namespace) -> int:
    """Handle ``autodev artifacts-cleanup``: garbage-collect unreferenced artifacts.

    Args:
        args: Parsed CLI arguments with ``dry_run`` and optional ``retention_days``.

    Returns:
        Process exit code, always ``0``.
    """
    from backend.artifacts import cleanup_unreferenced_artifacts, get_artifact_store

    store = get_artifact_store()
    result = cleanup_unreferenced_artifacts(
        store,
        dry_run=args.dry_run,
        retention_days=args.retention_days,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "dry_run": result.dry_run,
                "scanned_count": result.scanned_count,
                "removed": [
                    {
                        "bucket": obj.bucket,
                        "object_key": obj.object_key,
                        "size_bytes": obj.size_bytes,
                        "last_modified": obj.last_modified.isoformat(),
                    }
                    for obj in result.removed
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _handle_sdk_new_plugin(args: argparse.Namespace) -> int:
    """Handle ``autodev sdk new plugin``: scaffold a new plugin project.

    Args:
        args: Parsed CLI arguments, including ``plugin_id`` and ``output``.

    Returns:
        Process exit code, always ``0``.
    """
    from backend.sdk.scaffold import scaffold_plugin
    path = scaffold_plugin(args.plugin_id, Path(args.output))
    print(json.dumps({"status": "ok", "path": str(path)}, ensure_ascii=False))
    return 0


def _handle_config_set(args: argparse.Namespace) -> int:
    """Handle ``autodev config set``: update and persist runtime configuration fields.

    Args:
        args: Parsed CLI arguments with the optional fields to update.

    Returns:
        Process exit code, always ``0``.
    """
    config_service, _, _ = _build_runtime_services()
    config = config_service.load()

    if args.provider is not None:
        config.llm.provider = args.provider
    if args.model is not None:
        config.llm.model = args.model
    if args.base_url is not None:
        config.llm.base_url = args.base_url
    if args.temperature is not None:
        config.llm.temperature = args.temperature
    if args.api_key is not None:
        config.llm.api_key = args.api_key
    if args.project_root is not None:
        config.repository.project_root = args.project_root
    if args.repository_label is not None:
        config.repository.repository_label = args.repository_label
    if args.default_goal is not None:
        config.repository.default_goal = args.default_goal

    saved = config_service.update(config)
    config_service.apply_to_environment(saved)
    get_chat_model.cache_clear()
    print(json.dumps({"config": saved.model_dump()}, indent=2, ensure_ascii=False))
    return 0


def _handle_config_validate(args: argparse.Namespace) -> int:
    """Handle ``autodev config validate``: validate settings under a temporary profile/file override.

    Args:
        args: Parsed CLI arguments, including optional ``profile`` and ``settings_file``.

    Returns:
        Process exit code: ``0`` on success, ``1`` if settings fail to load.
    """
    old_profile = os.environ.get("AUTODEV_PROFILE")
    old_settings_file = os.environ.get("AUTODEV_SETTINGS_FILE")
    try:
        if args.profile is not None:
            os.environ["AUTODEV_PROFILE"] = args.profile
        if args.settings_file is not None:
            os.environ["AUTODEV_SETTINGS_FILE"] = args.settings_file
        reset_settings_cache()
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    finally:
        if old_profile is None:
            os.environ.pop("AUTODEV_PROFILE", None)
        else:
            os.environ["AUTODEV_PROFILE"] = old_profile
        if old_settings_file is None:
            os.environ.pop("AUTODEV_SETTINGS_FILE", None)
        else:
            os.environ["AUTODEV_SETTINGS_FILE"] = old_settings_file
        reset_settings_cache()

    print(
        json.dumps(
            {
                "status": "ok",
                "profile": settings.autodev_profile,
                "database_url": settings.database_url,
                "llm_provider": settings.llm_provider,
                "storage_backend": settings.storage_backend,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_sessions_list(_: argparse.Namespace) -> int:
    """Handle ``autodev sessions list``: print all persisted sessions.

    Returns:
        Process exit code, always ``0``.
    """
    _config, orchestrator, _repo = _build_runtime_services()
    sessions = orchestrator.list_sessions()
    print(
        json.dumps(
            [
                {
                    "session_id": session.session_id,
                    "goal": session.goal,
                    "plan": session.plan,
                    "status": session.status,
                    "history_length": len(session.history),
                }
                for session in sessions
            ],
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_plan_create(args: argparse.Namespace) -> int:
    """Handle ``autodev plan``: create a new planning session for a goal.

    Args:
        args: Parsed CLI arguments, including ``goal``.

    Returns:
        Process exit code, always ``0``.
    """
    _, orchestrator, _ = _build_runtime_services()
    session = orchestrator.create_plan(args.goal)
    print(json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _handle_run_message(args: argparse.Namespace) -> int:
    """Handle ``autodev run message``: send a message through the orchestrator.

    Args:
        args: Parsed CLI arguments, including ``session_id`` and ``message``.

    Returns:
        Process exit code, always ``0``.
    """
    _, orchestrator, _ = _build_runtime_services()
    run = orchestrator.handle_message(args.session_id, args.message)
    print(json.dumps(run.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _handle_execute_plan(args: argparse.Namespace) -> int:
    """Handle ``autodev run execute-plan``: execute a session's derived plan.

    Args:
        args: Parsed CLI arguments, including ``session_id``.

    Returns:
        Process exit code, always ``0``.
    """
    _, orchestrator, _ = _build_runtime_services()
    run = orchestrator.execute_plan(args.session_id)
    print(json.dumps(run.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _handle_repository_context(args: argparse.Namespace) -> int:
    """Handle ``autodev repository context``: print ranked repository search results.

    Args:
        args: Parsed CLI arguments, including ``query`` and ``limit``.

    Returns:
        Process exit code, always ``0``.
    """
    _, _, repository_service = _build_runtime_services()
    context = repository_service.build_context(
        query=args.query,
        limit=max(1, min(args.limit, 25)),
    )
    print(json.dumps(context.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _shell_base_url(args: argparse.Namespace) -> str:
    """Resolve the Control Plane API base URL for HTTP-only CLI commands (E14-S7).

    Mirrors ``backend.cli_shell``'s own resolution: an explicit ``--base-url``
    wins, then ``AUTODEV_SHELL_BASE_URL``, then the local default.
    """
    return args.base_url or os.environ.get("AUTODEV_SHELL_BASE_URL", "http://127.0.0.1:8000")


def _handle_permissions_list(args: argparse.Namespace) -> int:
    """Handle ``autodev permissions list`` (E14-S7): list dynamic permission grants.

    Calls ``GET /v2/execution/policy/dynamic`` over HTTP — the same
    HTTP-only pattern ``backend.cli_shell`` uses, not a direct
    ``PolicyService`` call, since this command is a CLI mirror of E14-S5's
    Web UX panel.

    Returns:
        Process exit code, always ``0``.
    """
    import httpx

    with httpx.Client(base_url=_shell_base_url(args), timeout=30.0) as client:
        response = client.get("/v2/execution/policy/dynamic")
        response.raise_for_status()
        permissions = response.json()["permissions"]

    if not permissions:
        print("No dynamic permissions granted.")
        return 0
    for permission in permissions:
        pattern = permission.get("pattern") or "*"
        print(f"{permission['permissionId']}  {permission['category']}  {pattern}")
    return 0


def _handle_permissions_revoke(args: argparse.Namespace) -> int:
    """Handle ``autodev permissions revoke <id>`` (E14-S7): revoke a dynamic permission.

    Calls ``DELETE /v2/execution/policy/dynamic/{id}`` over HTTP.

    Returns:
        Process exit code, always ``0``.
    """
    import httpx

    with httpx.Client(base_url=_shell_base_url(args), timeout=30.0) as client:
        response = client.delete(f"/v2/execution/policy/dynamic/{args.permission_id}")
        response.raise_for_status()
    print(f"Revoked {args.permission_id}")
    return 0


def _handle_doctor(_: argparse.Namespace) -> int:
    """Handle ``autodev doctor`` (E34-S2-T3): run preflight diagnostics.

    Returns:
        Process exit code: ``0`` if every check passed, ``1`` otherwise.
    """
    from backend.ops.doctor import diagnostics_ok, run_diagnostics

    checks = run_diagnostics()
    ok = diagnostics_ok(checks)
    print(
        json.dumps(
            {"status": "ok" if ok else "fail", "checks": [c.as_dict() for c in checks]},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


def _handle_bootstrap(_: argparse.Namespace) -> int:
    """Handle ``autodev bootstrap`` (E34-S2-T1): preflight-check then initialize the state store.

    Returns:
        Process exit code: ``0`` on success, ``1`` if preflight diagnostics failed.
    """
    from backend.ops.bootstrap import bootstrap

    result = bootstrap()
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    return 0 if result.status == "ok" else 1


def _handle_upgrade(args: argparse.Namespace) -> int:
    """Handle ``autodev upgrade`` (E34-S3-T1): back up, then migrate the state store.

    Args:
        args: Parsed CLI arguments, with optional ``backup_dir``/``target_version``.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the backup failed or the
        compatibility check refused the migration.
    """
    import datetime

    from backend.ops.upgrade import run_upgrade

    backup_dir = args.backup_dir or (
        f".autodev/upgrade-backups/{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}"
    )
    result = run_upgrade(backup_dir, target_version=args.target_version)
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    return 0 if result.status == "ok" else 1


def _handle_start_web(args: argparse.Namespace) -> int:
    """Handle ``autodev`` with no subcommand (E14-S7): start the server and open the browser.

    Starts ``backend.api.main:app`` under uvicorn on a background thread,
    waits for ``/health``, then opens the platform's existing E18 front
    door (``GET /``, which itself points at ``AUTODEV_UI_URL``) in the
    default browser. Runs until interrupted (``Ctrl+C``).

    Args:
        args: Parsed top-level CLI arguments (only ``AUTODEV_HOST``/
            ``AUTODEV_PORT`` env vars are consulted; no dedicated flags —
            keeps this story's surface to what its DoD asks for).

    Returns:
        Process exit code, always ``0``.
    """
    import threading
    import time
    import webbrowser

    import httpx
    import uvicorn

    from backend.api.main import app

    host = os.environ.get("AUTODEV_HOST", "127.0.0.1")
    port = int(os.environ.get("AUTODEV_PORT", "8000"))
    root_url = f"http://{host}:{port}/"

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 15.0
    with httpx.Client() as client:
        while time.monotonic() < deadline and thread.is_alive():
            try:
                if client.get(f"http://{host}:{port}/health", timeout=1.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)

    if thread.is_alive():
        try:
            webbrowser.open(root_url)
        except Exception:  # noqa: BLE001 - a missing/headless browser must not crash the server
            pass
        print(f"AutoDev is running at {root_url} (Ctrl+C to stop)")

    try:
        while thread.is_alive():
            thread.join(timeout=1.0)
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(timeout=5.0)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
