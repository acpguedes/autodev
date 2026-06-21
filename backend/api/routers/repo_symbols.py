"""Repository symbol extraction router.

Exposes ``GET /repository/symbols`` which accepts either a file path (``?path=``)
or raw source code (``?code=``) together with a ``?language=`` hint, and returns
the symbols extracted by the active :func:`get_provider`.

The router is auto-discovered by
:func:`backend.api.routers.include_all_routers` via the standard ``router``
attribute — no changes to ``main.py`` are required.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.repository.providers import get_provider

router = APIRouter(tags=["repository"])


class SymbolsResponse(BaseModel):
    symbols: List[str]
    provider: str


@router.get("/repository/symbols", response_model=SymbolsResponse)
def extract_symbols(
    path: str | None = Query(default=None, description="Path to a source file"),
    code: str | None = Query(default=None, description="Raw source code"),
    language: str = Query(default="python", description="Source language hint"),
) -> SymbolsResponse:
    """Extract top-level symbols from a source file or raw code snippet."""
    if path is not None:
        file_path = Path(path).expanduser()
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {path!r}")
        source = file_path.read_text(encoding="utf-8")
    elif code is not None:
        source = code
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either ?path= or ?code=.",
        )

    provider = get_provider()
    symbols = provider.extract_symbols(source, language)
    provider_name = type(provider).__name__.lower().replace("provider", "")
    return SymbolsResponse(symbols=symbols, provider=provider_name)


__all__ = ["router"]
