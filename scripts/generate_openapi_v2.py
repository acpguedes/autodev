#!/usr/bin/env python3
"""Generate the ``/v2`` Control Plane API's OpenAPI document (E9-S1-T4).

Loads the FastAPI application, restricts its published OpenAPI schema to
``/v2/*`` paths, and writes the result to ``docs/api/openapi_v2.json``.
Component schemas are left untouched (not pruned) since ``/v2`` handlers may
still reference shared models; this keeps the generated document a strict
superset that is safe for any downstream ``$ref`` resolution.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.api.main import app  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "docs" / "api" / "openapi_v2.json"


def build_v2_openapi_document() -> dict:
    """Build the ``/v2``-scoped OpenAPI document from the live FastAPI app.

    Returns:
        The full OpenAPI schema with ``paths`` restricted to entries whose
        path starts with ``/v2``.
    """
    schema = app.openapi()
    v2_paths = {path: item for path, item in schema.get("paths", {}).items() if path.startswith("/v2")}
    document = dict(schema)
    document["paths"] = v2_paths
    document["info"] = {
        **schema.get("info", {}),
        "title": f"{schema.get('info', {}).get('title', 'AutoDev Architect')} - Control Plane API /v2",
    }
    return document


def main() -> int:
    """Write the ``/v2`` OpenAPI document to :data:`OUTPUT_PATH`.

    Returns:
        Process exit code (always ``0`` on success).
    """
    document = build_v2_openapi_document()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(document['paths'])} /v2 paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
