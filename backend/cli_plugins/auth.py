"""CLI plugin for offline service-credential management (E11-S2 Task 2).

Registers ``autodev auth service-key create|list|revoke`` via the
``backend.cli_plugins`` auto-loader. Runs against the durable Auth Store
directly (no running server required), matching the offline
``autodev config validate``-style tooling convention.
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from typing import Any


def _handle_service_key_create(args: argparse.Namespace) -> int:
    """Mint a new service credential and print it (secret shown once)."""
    from backend.auth.roles import normalize_role, normalize_scopes  # noqa: PLC0415
    from backend.auth.service import AuthService  # noqa: PLC0415
    from backend.auth.store import utcnow  # noqa: PLC0415
    from backend.config.settings import get_settings  # noqa: PLC0415

    try:
        roles = tuple(normalize_role(role) for role in args.role)
        scopes = normalize_scopes(args.scope) if args.scope else frozenset()
        service = AuthService(get_settings())
        record, key = service.create_service_key(
            tenant_id=args.tenant_id,
            subject=args.subject,
            roles=roles,
            scopes=scopes,
            expires_at=utcnow() + timedelta(days=args.expires_in_days),
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=__import__("sys").stderr)
        return 1

    print(
        json.dumps(
            {
                "keyId": record.key_id,
                "tenantId": record.tenant_id,
                "subject": record.subject,
                "roles": [role.value for role in record.roles],
                "scopes": sorted(record.scopes),
                "expiresAt": record.expires_at.isoformat(),
                "key": key,
                "warning": "This key is shown once and cannot be recovered.",
            },
            indent=2,
        )
    )
    return 0


def _handle_service_key_list(args: argparse.Namespace) -> int:
    """List service credentials for a tenant (never includes a secret)."""
    from backend.auth.service import AuthService  # noqa: PLC0415
    from backend.config.settings import get_settings  # noqa: PLC0415

    service = AuthService(get_settings())
    records = service.list_service_keys(tenant_id=args.tenant_id)
    print(
        json.dumps(
            [
                {
                    "keyId": record.key_id,
                    "subject": record.subject,
                    "roles": [role.value for role in record.roles],
                    "scopes": sorted(record.scopes),
                    "createdAt": record.created_at.isoformat(),
                    "expiresAt": record.expires_at.isoformat(),
                    "active": record.is_active,
                }
                for record in records
            ],
            indent=2,
        )
    )
    return 0


def _handle_service_key_revoke(args: argparse.Namespace) -> int:
    """Immediately revoke one service credential."""
    from backend.auth.service import AuthService  # noqa: PLC0415
    from backend.config.settings import get_settings  # noqa: PLC0415

    service = AuthService(get_settings())
    revoked = service.revoke_service_key(tenant_id=args.tenant_id, key_id=args.key_id)
    print(json.dumps({"keyId": args.key_id, "revoked": revoked}))
    return 0 if revoked else 1


def register(subparsers: Any) -> None:
    """Add the ``auth`` sub-tree to the CLI argument parser."""
    auth_parser = subparsers.add_parser("auth", help="Manage Control Plane authentication")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)

    service_key_parser = auth_subparsers.add_parser(
        "service-key", help="Manage governed service credentials"
    )
    service_key_subparsers = service_key_parser.add_subparsers(
        dest="service_key_command", required=True
    )

    create_parser = service_key_subparsers.add_parser("create", help="Mint a new service key")
    create_parser.add_argument("--tenant-id", required=True)
    create_parser.add_argument("--subject", required=True)
    create_parser.add_argument("--role", action="append", required=True, dest="role")
    create_parser.add_argument("--scope", action="append", default=[], dest="scope")
    create_parser.add_argument("--expires-in-days", type=int, required=True)
    create_parser.set_defaults(handler=_handle_service_key_create)

    list_parser = service_key_subparsers.add_parser("list", help="List service keys for a tenant")
    list_parser.add_argument("--tenant-id", required=True)
    list_parser.set_defaults(handler=_handle_service_key_list)

    revoke_parser = service_key_subparsers.add_parser("revoke", help="Revoke a service key")
    revoke_parser.add_argument("--tenant-id", required=True)
    revoke_parser.add_argument("--key-id", required=True)
    revoke_parser.set_defaults(handler=_handle_service_key_revoke)
