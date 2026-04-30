"""WebSocket chat endpoint.

Protocol (server -> client): the same StepEvent JSON the agent-runtime
emits, framed one-per-message.

Auth: looks for the session cookie OR a ``token`` query parameter for
clients that can't pass cookies on WS handshake.
"""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

import httpx
from agenticos_shared.auth import Principal
from agenticos_shared.errors import UnauthorizedError
from agenticos_shared.logging import get_logger
from agenticos_shared.models import Agent, Session, WorkspaceMember
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from ..auth.session import decode_session
from ..db import get_db
from ..settings import Settings, get_settings

router = APIRouter(tags=["chat"])
log = get_logger(__name__)


def _principal_from_ws(
    ws: WebSocket, settings: Settings, db: DBSession, token: str | None
) -> Principal:
    cookie = ws.cookies.get(settings.session_cookie_name)
    raw = token or cookie
    if not raw:
        raise UnauthorizedError("not authenticated")
    payload = decode_session(raw, secret=settings.secret_key)
    if payload.is_expired():
        raise UnauthorizedError("session expired")
    from agenticos_shared.models import User

    user = db.get(User, payload.user_id)
    if user is None:
        raise UnauthorizedError("user not found")

    rows = db.execute(
        select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(
            WorkspaceMember.user_id == user.id
        )
    ).all()
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        display_name=user.display_name,
        roles=sorted({r for _, r in rows}) + (["superuser"] if user.is_superuser else []),
        workspace_ids=[w for w, _ in rows],
    )


@router.websocket("/chat/{agent_id}/ws")
async def chat_ws(
    ws: WebSocket,
    agent_id: UUID,
    token: Annotated[str | None, Query()] = None,
    session_id: Annotated[UUID | None, Query()] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
    db: Annotated[DBSession, Depends(get_db)] = None,  # type: ignore[assignment]
):
    await ws.accept()

    try:
        principal = _principal_from_ws(ws, settings, db, token)
    except UnauthorizedError as exc:
        await ws.send_json({"type": "error", "payload": {"message": exc.detail or "unauthorized"}})
        await ws.close(code=4401)
        return

    agent = db.get(Agent, agent_id)
    if agent is None:
        await ws.send_json({"type": "error", "payload": {"message": "agent not found"}})
        await ws.close(code=4404)
        return

    # Workspace membership.
    if agent.workspace_id not in principal.workspace_ids and "superuser" not in principal.roles:
        await ws.send_json({"type": "error", "payload": {"message": "forbidden"}})
        await ws.close(code=4403)
        return

    # Resolve / create the session.
    if session_id is None:
        from uuid import uuid4

        from agenticos_shared.models import Session as SessionRow

        session = SessionRow(
            id=uuid4(),
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            user_id=principal.user_id,
            meta={},
        )
        db.add(session)
        db.commit()
    else:
        session = db.get(Session, session_id)
        if session is None or session.workspace_id != agent.workspace_id:
            await ws.send_json({"type": "error", "payload": {"message": "session not found"}})
            await ws.close(code=4404)
            return

    await ws.send_json(
        {
            "type": "session",
            "payload": {"session_id": str(session.id), "agent_id": str(agent_id)},
        }
    )

    runtime_url = settings.agent_runtime_url.rstrip("/")

    try:
        while True:
            try:
                msg = await ws.receive_json()
            except WebSocketDisconnect:
                return
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if kind == "user_message":
                user_text = (msg.get("content") or "").strip()
                if not user_text:
                    continue
                payload = {
                    "agent_id": str(agent.id),
                    "session_id": str(session.id),
                    "user_message": user_text,
                }
                try:
                    async with (
                        httpx.AsyncClient(timeout=600.0) as c,
                        c.stream("POST", f"{runtime_url}/run/stream", json=payload) as r,
                    ):
                        async for line in r.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[len("data: ") :]
                            if data == "[DONE]":
                                await ws.send_json({"type": "done", "payload": {}})
                                break
                            try:
                                event = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            await ws.send_json(event)
                except Exception as exc:
                    log.warning("ws_stream_failed", error=str(exc))
                    await ws.send_json({"type": "error", "payload": {"message": str(exc)[:300]}})
            elif kind == "ping":
                await ws.send_json({"type": "pong", "payload": {}})
    except WebSocketDisconnect:
        return
