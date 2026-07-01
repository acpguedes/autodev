"""Utility script to launch the FastAPI orchestrator with uvicorn.

Bind address, port, and autoreload are read from the environment so the default
is safe (loopback, no reload) while deployments can opt into broader exposure
explicitly:

* ``AUTODEV_HOST``  — interface to bind (default ``127.0.0.1``).
* ``AUTODEV_PORT``  — port to bind (default ``8000``).
* ``UVICORN_RELOAD`` — set to a truthy value to enable autoreload (dev only).
"""

from __future__ import annotations

import os

import uvicorn

_TRUTHY = {"1", "true", "yes", "on"}


def main() -> None:
    host = os.getenv("AUTODEV_HOST", "127.0.0.1")
    port = int(os.getenv("AUTODEV_PORT", "8000"))
    reload = os.getenv("UVICORN_RELOAD", "false").strip().lower() in _TRUTHY
    uvicorn.run("backend.api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
