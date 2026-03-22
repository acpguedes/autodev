"""Structured CLI for local AutoDev Architect operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from backend.config import RuntimeConfigService
from backend.llm.factory import get_chat_model
from backend.orchestrator.service import OrchestratorService
from backend.persistence.database import reset_store_cache
from backend.repository import RepositoryIntelligenceService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autodev",
        description="CLI estruturada para configurar e operar o AutoDev Architect localmente.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


def _build_runtime_services() -> tuple[RuntimeConfigService, OrchestratorService, RepositoryIntelligenceService]:
    config_service = RuntimeConfigService()
    runtime_config = config_service.apply_to_environment()
    get_chat_model.cache_clear()
    reset_store_cache()
    project_root = Path(runtime_config.repository.project_root)
    orchestrator = OrchestratorService(project_root=project_root)
    repository_service = RepositoryIntelligenceService(project_root=project_root)
    return config_service, orchestrator, repository_service


def _handle_config_show(args: argparse.Namespace) -> int:
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


def _handle_config_set(args: argparse.Namespace) -> int:
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


def _handle_sessions_list(_: argparse.Namespace) -> int:
    _, orchestrator, _ = _build_runtime_services()
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
    _, orchestrator, _ = _build_runtime_services()
    session = orchestrator.create_plan(args.goal)
    print(json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _handle_run_message(args: argparse.Namespace) -> int:
    _, orchestrator, _ = _build_runtime_services()
    run = orchestrator.handle_message(args.session_id, args.message)
    print(json.dumps(run.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _handle_execute_plan(args: argparse.Namespace) -> int:
    _, orchestrator, _ = _build_runtime_services()
    run = orchestrator.execute_plan(args.session_id)
    print(json.dumps(run.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _handle_repository_context(args: argparse.Namespace) -> int:
    _, _, repository_service = _build_runtime_services()
    context = repository_service.build_context(
        query=args.query,
        limit=max(1, min(args.limit, 25)),
    )
    print(json.dumps(context.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
