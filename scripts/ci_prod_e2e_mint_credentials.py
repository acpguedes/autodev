"""CI step: mint two tenants' service credentials for the prod E2E (E57-S3).

Writes the credentials directly into the Auth Store against the target
PostgreSQL database -- the same store the live server will read from once
it boots -- rather than going through the API (there is no API yet; this
runs before the server starts). Two tenants, not one, so the smoke script
can prove Row-Level Security both directions (E57-S3-T2) over the API: a
service key genuinely scopes every request to its own ``tenant_id``
(``backend/auth/service.py:authenticate_service_key``).

Usage:
    python scripts/ci_prod_e2e_mint_credentials.py <postgresql-database-url> <github-env-file>

Appends ``AUTODEV_E2E_TENANT_A_KEY``/``AUTODEV_E2E_TENANT_B_KEY`` (and their
tenant ids) to *github-env-file* (``$GITHUB_ENV``) for later steps.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.auth.roles import Role  # noqa: E402
from backend.auth.service import AuthService  # noqa: E402
from backend.auth.store import AuthStore  # noqa: E402
from backend.config.settings import Settings  # noqa: E402
from backend.persistence.postgres_adapter import PostgresStore  # noqa: E402

#: Service keys are minted with a short but valid TTL (1-90 days is the
#: enforced range; a CI job never runs anywhere near a full day).
_KEY_TTL = timedelta(days=1)


def main(argv: list[str] | None = None) -> int:
    """Mint one service credential per tenant and append them to the GitHub env file.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``); expects
            ``(database_url, github_env_file)``.

    Returns:
        ``0`` on success, ``2`` on a usage error.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "usage: ci_prod_e2e_mint_credentials.py <database_url> <github_env_file>",
            file=sys.stderr,
        )
        return 2
    database_url, github_env_file = args

    store = PostgresStore(database_url)
    auth_store = AuthStore(store=store)
    # AuthService only reads settings for OIDC configuration, unused by
    # service-key minting; the profile/database here are unrelated to the
    # server this credential will authenticate against.
    settings = Settings(autodev_profile="local", database_url="sqlite:///:memory:")
    service = AuthService(settings=settings, store=auth_store)

    tenant_a = f"e2e-tenant-a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"e2e-tenant-b-{uuid.uuid4().hex[:8]}"
    expires_at = datetime.now(timezone.utc) + _KEY_TTL

    _, key_a = service.create_service_key(
        tenant_id=tenant_a,
        subject="ci-e2e-tenant-a",
        roles=(Role.OWNER,),
        scopes=frozenset(),
        expires_at=expires_at,
    )
    _, key_b = service.create_service_key(
        tenant_id=tenant_b,
        subject="ci-e2e-tenant-b",
        roles=(Role.OWNER,),
        scopes=frozenset(),
        expires_at=expires_at,
    )

    with open(github_env_file, "a") as handle:
        handle.write(f"AUTODEV_E2E_TENANT_A={tenant_a}\n")
        handle.write(f"AUTODEV_E2E_TENANT_A_KEY={key_a}\n")
        handle.write(f"AUTODEV_E2E_TENANT_B={tenant_b}\n")
        handle.write(f"AUTODEV_E2E_TENANT_B_KEY={key_b}\n")

    print(f"[mint] minted service credentials for tenants {tenant_a!r} and {tenant_b!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
