from __future__ import annotations

from backend.sdk.contracts import HostApi


def register(host: HostApi) -> None:
    host.register_extension("skill", "autodev/hello-plugin.skill", {"label": "Hello plugin"})
