"""CI step: exercise a real prod-profile flow over HTTP (E57-S3).

Runs against the already-booted, already-authenticated live server (the
boot itself, under real ``validate_profile``, is S3-T1's proof). Proves,
for real, over HTTP, against real PostgreSQL/Redis/MinIO:

* a session create/read round trip, which drives the planner agent for
  real (S3-T2's "API end-to-end flow");
* two-tenant Row-Level Security, both directions: tenant B cannot read
  tenant A's session and vice versa (S3-T2's "two-tenant RLS check
  asserting both directions of the boundary") -- via two independently
  minted service credentials (``scripts/ci_prod_e2e_mint_credentials.py``),
  not OIDC;
* a real vector query through hybrid retrieval (S3-T2): seeds one chunk via
  the production ``index()`` ingestion pipeline and
  :func:`~backend.repository.embeddings.pgvector_store.upsert_embeddings`,
  then queries ``/v2/context/retrieve?mode=vector`` over HTTP and asserts
  the seeded content comes back -- and that it does *not* come back for the
  other tenant (RLS on the vector path too).

``--post-restore`` additionally proves the three other functional checks
E59-S2-T2 requires of a clean-environment restore -- not merely that the
restore command exited zero:

* secret resolution: the pre-backup run creates a real secret over
  ``POST /v2/secrets``; post-restore, its metadata is still listed over
  ``GET /v2/secrets`` and :meth:`~backend.secret_store.service.SecretService.resolve_for_injection`
  still decrypts it to the original plaintext -- proving the encrypted
  value and the encryption key configuration both survived the round trip;
* artifact resolution: the pre-backup run writes one object through the
  public artifact-store API used elsewhere in this repository
  (:mod:`backend.persistence.backup`); post-restore, the same object is
  read back byte-for-byte;
* the vector query is rerun post-restore (not just structurally verified)
  to prove the HNSW index is usable, not merely present, after restore.

Deliberately not attempted here: a full multi-step plan/approve/execute
task run through the stub LLM's agent orchestration -- that is separate,
substantial new test surface (an "analyze" trigger, task derivation, a
successful execute path) beyond what any existing test in this repository
already exercises, and is out of this epic's CI-wiring scope. E57-S3-T3
(concurrency invariants against the real stack) is satisfied by the
``backend-tests-postgres`` CI job running the E51-E55 real-connection
concurrency suites (E57-S2), not by this script.

Usage:
    python scripts/ci_prod_e2e_smoke.py <base_url> <database_url> [--post-restore]

``--post-restore`` (E57-S4-T2) skips writing new data -- the backup/restore
round trip already ran between the two invocations -- and instead lists
sessions as each tenant, asserting the session this script created on the
first (pre-backup) run is still there: proof the restored environment
actually serves data, not merely that the restore command exited zero.

Reads ``AUTODEV_E2E_TENANT_A``/``_KEY`` and ``AUTODEV_E2E_TENANT_B``/``_KEY``
from the environment (set by ``ci_prod_e2e_mint_credentials.py`` via
``$GITHUB_ENV``).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from backend.persistence.postgres_adapter import PostgresStore  # noqa: E402
from backend.persistence.tenancy import set_postgres_tenant  # noqa: E402
from backend.repository.embeddings.pgvector_store import upsert_embeddings  # noqa: E402
from backend.repository.embeddings.provider import StubEmbeddingProvider  # noqa: E402
from backend.repository.indexing import index  # noqa: E402

_SEED_QUERY_TEXT = "def autodev_e57_vector_probe(): return 'e57-hybrid-retrieval-proof'"
_SESSION_GOAL = "E57 prod E2E: session flow proof"
_SESSION_GOAL_TENANT_B = "E57 prod E2E: session flow proof (tenant B)"

#: Fixed (non-random) secret/artifact identifiers so the post-restore run,
#: a separate process, can recompute them without inter-process state.
_SECRET_PROJECT = "e59-drill"
_SECRET_NAME = "backup-restore-probe"
_SECRET_VALUE = "e59-backup-drill-secret-value"
_ARTIFACT_OBJECT_SUFFIX = "e59-drill/probe.log"
_ARTIFACT_PAYLOAD = b"e59-backup-drill-artifact-probe"


def _wait_for_health(client: httpx.Client, *, timeout_s: float = 60.0) -> None:
    """Poll ``/health`` until it responds 200, or raise after *timeout_s*."""
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"server did not become healthy in {timeout_s}s: {last_error}")


def _auth_headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _check_session_flow_and_cross_tenant_rls(client: httpx.Client) -> None:
    """Create a session as tenant A; prove tenant B cannot read it and vice versa."""
    key_a = os.environ["AUTODEV_E2E_TENANT_A_KEY"]
    key_b = os.environ["AUTODEV_E2E_TENANT_B_KEY"]

    created_a = client.post("/v2/sessions", json={"goal": _SESSION_GOAL}, headers=_auth_headers(key_a))
    assert created_a.status_code == 201, created_a.text
    session_a = created_a.json()["session_id"]

    created_b = client.post(
        "/v2/sessions", json={"goal": _SESSION_GOAL_TENANT_B}, headers=_auth_headers(key_b)
    )
    assert created_b.status_code == 201, created_b.text
    session_b = created_b.json()["session_id"]

    get_own_a = client.get(f"/v2/sessions/{session_a}", headers=_auth_headers(key_a))
    assert get_own_a.status_code == 200, get_own_a.text

    cross_b_reads_a = client.get(f"/v2/sessions/{session_a}", headers=_auth_headers(key_b))
    assert cross_b_reads_a.status_code == 404, (
        f"tenant B read tenant A's session: {cross_b_reads_a.status_code} {cross_b_reads_a.text}"
    )
    cross_a_reads_b = client.get(f"/v2/sessions/{session_b}", headers=_auth_headers(key_a))
    assert cross_a_reads_b.status_code == 404, (
        f"tenant A read tenant B's session: {cross_a_reads_b.status_code} {cross_a_reads_b.text}"
    )
    print("[smoke] session create/read + two-tenant RLS (both directions): OK")


def _seed_vector_chunk(database_url: str, tenant_id: str) -> None:
    """Index one known file's content for *tenant_id* and embed it (real pipeline, real pgvector)."""
    import tempfile

    store = PostgresStore(database_url)
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "e57_probe.py"
        sample.write_text(_SEED_QUERY_TEXT + "\n")
        written = index(tmp, tenant_id=tenant_id, store=store)
        assert written > 0, "index() wrote no chunks for the seeded probe file"

    with store.connect() as conn:
        set_postgres_tenant(conn, tenant_id)
        rows = conn.execute(
            "SELECT id, content, content_hash FROM code_chunks WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchall()
        upserted = upsert_embeddings(conn, list(rows), StubEmbeddingProvider(), tenant_id=tenant_id)
        conn.commit()
    assert upserted > 0, "upsert_embeddings() embedded no chunks"
    print(f"[smoke] seeded {upserted} chunk embedding(s) for tenant {tenant_id!r}")


def _check_vector_query(client: httpx.Client) -> None:
    """Query the seeded chunk via /v2/context/retrieve (mode=vector) and assert it comes back, tenant-scoped."""
    key_a = os.environ["AUTODEV_E2E_TENANT_A_KEY"]
    key_b = os.environ["AUTODEV_E2E_TENANT_B_KEY"]

    own_tenant = client.get(
        "/v2/context/retrieve",
        params={"query": _SEED_QUERY_TEXT, "mode": "vector", "limit": 5},
        headers=_auth_headers(key_a),
    )
    assert own_tenant.status_code == 200, own_tenant.text
    results = own_tenant.json()["results"]
    assert results, "vector query returned no results for the tenant that owns the seeded chunk"
    assert any("autodev_e57_vector_probe" in r["content"] for r in results), results

    other_tenant = client.get(
        "/v2/context/retrieve",
        params={"query": _SEED_QUERY_TEXT, "mode": "vector", "limit": 5},
        headers=_auth_headers(key_b),
    )
    assert other_tenant.status_code == 200, other_tenant.text
    assert other_tenant.json()["results"] == [], "tenant B's vector query saw tenant A's chunk (RLS leak)"
    print("[smoke] real vector query through hybrid retrieval, tenant-scoped: OK")


def _create_secret_over_api(client: httpx.Client, key: str) -> None:
    """Create the drill secret over ``POST /v2/secrets`` (real API path)."""
    response = client.post(
        "/v2/secrets",
        json={"project": _SECRET_PROJECT, "name": _SECRET_NAME, "value": _SECRET_VALUE},
        headers=_auth_headers(key),
    )
    assert response.status_code == 201, response.text
    print("[smoke] created drill secret over POST /v2/secrets")


def _write_artifact_probe(tenant_id: str) -> None:
    """Write one object through the public artifact-store API (E59-S2-T2)."""
    from backend.artifacts.store import ArtifactKind, get_artifact_store
    from backend.config.settings import get_settings

    store = get_artifact_store(get_settings())
    object_key = f"{tenant_id}/{_ARTIFACT_OBJECT_SUFFIX}"
    store.put_artifact(ArtifactKind.LOG, object_key, _ARTIFACT_PAYLOAD)
    print(f"[smoke] wrote artifact probe {object_key!r}")


def _check_secret_resolution(client: httpx.Client, key: str, tenant_id: str) -> None:
    """Post-restore: the drill secret's metadata and plaintext both survive (E59-S2-T2)."""
    from backend.config.settings import get_settings
    from backend.secret_store.contracts import SecretReference
    from backend.secret_store.service import SecretService

    listed = client.get("/v2/secrets", params={"project": _SECRET_PROJECT}, headers=_auth_headers(key))
    assert listed.status_code == 200, listed.text
    names = [s["name"] for s in listed.json()["secrets"]]
    assert _SECRET_NAME in names, f"drill secret metadata did not survive restore: {names}"

    service = SecretService(settings=get_settings())
    reference = SecretReference(tenant_id=tenant_id, project=_SECRET_PROJECT, name=_SECRET_NAME)
    handle = service.resolve_for_injection(reference, actor_id="e59-backup-drill")
    assert handle.value == _SECRET_VALUE, "restored secret decrypted to the wrong plaintext"
    print("[smoke] post-restore secret resolution (metadata + decrypted value): OK")


def _check_artifact_resolution(tenant_id: str) -> None:
    """Post-restore: the drill artifact reads back byte-for-byte (E59-S2-T2).

    Resolves ``ArtifactKind.LOG``'s bucket purely via the public API -- the
    same positional-pairing technique
    :mod:`backend.persistence.backup` uses -- rather than importing the
    store's private kind-to-bucket table.
    """
    from backend.artifacts.store import ArtifactKind, all_bucket_names, get_artifact_store
    from backend.config.settings import get_settings

    store = get_artifact_store(get_settings())
    bucket = dict(zip(ArtifactKind, all_bucket_names()))[ArtifactKind.LOG]
    object_key = f"{tenant_id}/{_ARTIFACT_OBJECT_SUFFIX}"
    payload = store.get_artifact(bucket, object_key)
    assert payload == _ARTIFACT_PAYLOAD, "drill artifact did not survive restore byte-for-byte"
    print(f"[smoke] post-restore artifact resolution ({bucket}/{object_key}): OK")


def _check_post_restore_listing(client: httpx.Client) -> None:
    """List sessions as each tenant; assert the pre-backup session survived the restore."""
    key_a = os.environ["AUTODEV_E2E_TENANT_A_KEY"]
    key_b = os.environ["AUTODEV_E2E_TENANT_B_KEY"]

    listed_a = client.get("/v2/sessions", params={"limit": 20}, headers=_auth_headers(key_a))
    assert listed_a.status_code == 200, listed_a.text
    goals_a = [item["goal"] for item in listed_a.json()["items"]]
    assert _SESSION_GOAL in goals_a, f"tenant A's pre-backup session did not survive restore: {goals_a}"

    listed_b = client.get("/v2/sessions", params={"limit": 20}, headers=_auth_headers(key_b))
    assert listed_b.status_code == 200, listed_b.text
    goals_b = [item["goal"] for item in listed_b.json()["items"]]
    assert _SESSION_GOAL_TENANT_B in goals_b, f"tenant B's pre-backup session did not survive restore: {goals_b}"

    print("[smoke] post-restore session listing for both tenants: OK")


def main(argv: list[str] | None = None) -> int:
    """Run the prod E2E HTTP smoke checks.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``); expects
            ``(base_url, database_url)``, optionally followed by
            ``--post-restore``.

    Returns:
        ``0`` on success, ``2`` on a usage error. Any assertion failure
        propagates, exiting non-zero with a traceback.
    """
    args = sys.argv[1:] if argv is None else argv
    post_restore = "--post-restore" in args
    positional = [a for a in args if a != "--post-restore"]
    if len(positional) != 2:
        print("usage: ci_prod_e2e_smoke.py <base_url> <database_url> [--post-restore]", file=sys.stderr)
        return 2
    base_url, database_url = positional
    tenant_a = os.environ["AUTODEV_E2E_TENANT_A"]
    key_a = os.environ["AUTODEV_E2E_TENANT_A_KEY"]

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        _wait_for_health(client)
        print("[smoke] server is healthy")

        if post_restore:
            _check_post_restore_listing(client)
            _check_secret_resolution(client, key_a, tenant_a)
            _check_artifact_resolution(tenant_a)
            _check_vector_query(client)
        else:
            _check_session_flow_and_cross_tenant_rls(client)
            _seed_vector_chunk(database_url, tenant_a)
            _check_vector_query(client)
            _create_secret_over_api(client, key_a)
            _write_artifact_probe(tenant_a)

    print("[smoke] OK: all prod E2E checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
