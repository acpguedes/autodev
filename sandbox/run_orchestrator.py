"""Utility script to launch the FastAPI orchestrator with uvicorn."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("backend.api.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
