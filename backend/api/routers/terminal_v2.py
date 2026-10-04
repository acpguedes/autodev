"""v2 Control Plane API — interactive terminal over WebSocket (E65-S2).

``WS /v2/terminal/{terminal_id}`` is a deliberately narrow route, not the
general ``WS /v2/ws`` channel reserved in reference §14.4. The handshake is
authorized by :func:`~backend.api.authorization.authorize_websocket` (the
ambient app-level dependency cannot run on a WebSocket), and the project root
is always resolved server-side, never taken from the client.

Frames (JSON): client ``{"type":"input","data":str}`` and
``{"type":"resize","cols":int,"rows":int}``; server ``{"type":"info",
"projectRoot":str,"terminalId":str}``, ``{"type":"output","data":str}`` and
``{"type":"exit","code":int|null}``. Terminal output is never logged.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.api.authorization import authorize_websocket, public_endpoint, requires_scope
from backend.api.rbac_v2 import PrincipalV2, require_v2_principal
from backend.events.runtime import emit_event
from backend.projects.resolution import resolve_project, resolve_project_root, session_id_from_request
from backend.terminal.manager import TerminalCapError, get_terminal_manager, terminal_enabled

router = APIRouter(prefix="/v2/terminal", tags=["terminal"])

_MAX_INPUT_CHARS = 64 * 1024


class TerminalStatusV2(BaseModel):
    """Whether the terminal feature is enabled for this deployment."""

    enabled: bool


@router.get("/status", response_model=TerminalStatusV2)
@requires_scope("terminal:use")
def terminal_status_v2(principal: PrincipalV2 = Depends(require_v2_principal)) -> TerminalStatusV2:
    """Report whether the terminal is enabled (fail-closed flag).

    Args:
        principal: Authenticated caller (must hold ``terminal:use``).

    Returns:
        The enabled state.
    """
    return TerminalStatusV2(enabled=terminal_enabled())


def _emit(type_: str, tenant_id: str, terminal_id: str, project_id: str) -> None:
    emit_event(
        type_,
        tenant_id=tenant_id,
        partition_key=tenant_id,
        data={"tenantId": tenant_id, "terminalId": terminal_id, "projectId": project_id},
    )


@router.websocket("/{terminal_id}")
@public_endpoint
async def terminal_socket_v2(websocket: WebSocket, terminal_id: str) -> None:
    """Attach the caller to a persistent project-bound shell.

    Closes before ``accept()`` with 4403 when the feature is disabled or the
    caller lacks ``terminal:use``, and 4401 when unauthenticated.

    Args:
        websocket: The incoming socket.
        terminal_id: Client-generated terminal id.
    """
    if not terminal_enabled():
        await websocket.close(code=4403)
        return
    principal = await authorize_websocket(websocket, "terminal:use")
    if principal is None:
        return
    tenant_id = principal.tenant_id
    session_id = session_id_from_request(websocket)
    root = resolve_project_root(tenant_id=tenant_id, session_id=session_id)
    record = resolve_project(tenant_id=tenant_id, session_id=session_id)
    project_id = record.project_id if record is not None else ""
    try:
        session, created = get_terminal_manager().attach(tenant_id, root, terminal_id)
    except TerminalCapError:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def put(frame: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, frame)

    await websocket.send_json({"type": "info", "projectRoot": str(root), "terminalId": terminal_id})
    backlog = session.scrollback()
    if backlog:
        await websocket.send_json({"type": "output", "data": backlog.decode("utf-8", "replace")})
    unsubscribe = session.subscribe(
        lambda chunk: put({"type": "output", "data": chunk.decode("utf-8", "replace")}),
        lambda code: put({"type": "exit", "code": code}),
    )
    if created:
        _emit("terminal.session.opened", tenant_id, terminal_id, project_id)

    async def pump() -> None:
        while True:
            frame = await queue.get()
            await websocket.send_json(frame)
            if frame["type"] == "exit":
                return

    pump_task = asyncio.create_task(pump())
    try:
        while not pump_task.done():
            receive = asyncio.create_task(websocket.receive_text())
            done, _ = await asyncio.wait({receive, pump_task}, return_when=asyncio.FIRST_COMPLETED)
            if receive not in done:
                receive.cancel()
                break
            try:
                frame = json.loads(receive.result())
            except (json.JSONDecodeError, TypeError):
                continue
            kind = frame.get("type") if isinstance(frame, dict) else None
            if kind == "input" and isinstance(frame.get("data"), str):
                session.write(frame["data"][:_MAX_INPUT_CHARS].encode("utf-8"))
            elif kind == "resize" and isinstance(frame.get("cols"), int) and isinstance(frame.get("rows"), int):
                session.resize(frame["cols"], frame["rows"])
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe()
        pump_task.cancel()
        if not session.alive:
            _emit("terminal.session.closed", tenant_id, terminal_id, project_id)
        get_terminal_manager().sweep()
