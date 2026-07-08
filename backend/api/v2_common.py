"""Shared primitives for the ``/v2`` Control Plane API (E9-S1-T2).

Every new ``/v2`` resource added for E9-S1 (sessions, runs, execution plans,
config) shares three conventions defined here:

* :data:`SCHEMA_VERSION_V2` — stamped as the literal ``schemaVersion`` field
  on every *response* payload (not on request bodies: the URL's ``/v2``
  prefix already pins the request contract version, matching the existing
  ``schemaVersion``-on-output convention in
  ``backend/api/routers/flows.py`` and ``backend/skills/registry_v2.py``).
* :class:`PaginationParams` / :func:`paginate` — a single ``limit``/
  ``offset`` convention for every list endpoint, applied at the API
  boundary because the backing services (e.g.
  :meth:`backend.orchestrator.service.OrchestratorService.list_sessions`)
  return full, unpaginated collections.
* :func:`v2_error` — a standardized error envelope for domain errors that
  handlers raise deliberately (404 not found, 400 invalid state, ...).
  FastAPI's built-in request-validation errors (422) already use one
  consistent shape across this codebase and are intentionally left as-is.
"""

from __future__ import annotations

from typing import NoReturn, Sequence, TypeVar

from fastapi import HTTPException, Query
from pydantic import BaseModel

SCHEMA_VERSION_V2 = "2.0"
"""Wire schema version stamped on every ``/v2`` response payload."""

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 200

T = TypeVar("T")


class PaginationParams:
    """FastAPI dependency capturing the shared ``limit``/``offset`` query parameters."""

    def __init__(
        self,
        limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT, description="Max items to return."),
        offset: int = Query(default=0, ge=0, description="Number of items to skip."),
    ) -> None:
        """Capture the requested page window.

        Args:
            limit: Maximum number of items to return (1-200).
            offset: Number of items to skip from the start of the collection.
        """
        self.limit = limit
        self.offset = offset


class PageMetaV2(BaseModel):
    """Pagination metadata attached to every ``/v2`` list response."""

    limit: int
    offset: int
    total: int


def paginate(items: Sequence[T], params: PaginationParams) -> tuple[list[T], PageMetaV2]:
    """Slice an already-fetched collection according to *params*.

    Args:
        items: The full, unpaginated result set returned by the backing
            service.
        params: The requested ``limit``/``offset`` window.

    Returns:
        A tuple of the page slice and its :class:`PageMetaV2`.
    """
    total = len(items)
    page = list(items[params.offset : params.offset + params.limit])
    return page, PageMetaV2(limit=params.limit, offset=params.offset, total=total)


def v2_error(status_code: int, message: str) -> NoReturn:
    """Raise an :class:`HTTPException` carrying the standardized ``/v2`` error envelope.

    Args:
        status_code: HTTP status code to respond with.
        message: Human-readable error message.

    Raises:
        HTTPException: Always. Its ``detail`` is
            ``{"schemaVersion": SCHEMA_VERSION_V2, "error": {"code": status_code, "message": message}}``.
    """
    raise HTTPException(
        status_code=status_code,
        detail={"schemaVersion": SCHEMA_VERSION_V2, "error": {"code": status_code, "message": message}},
    )


__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "PageMetaV2",
    "PaginationParams",
    "SCHEMA_VERSION_V2",
    "paginate",
    "v2_error",
]
