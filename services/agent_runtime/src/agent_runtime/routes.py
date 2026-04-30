"""Internal HTTP API for agent-runtime.

The api-gateway calls these to start a run; it streams events back over
its WebSocket layer.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID, uuid4

from agenticos_shared.db import get_sessionmaker
from agenticos_shared.errors import NotFoundError
from agenticos_shared.models import Agent, Message, Session
from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .runner import event_to_ws, run_agent
from .schemas import AgentSpec, RunResult
from .settings import Settings, get_settings
from .state import get_proxies, get_publish

router = APIRouter(tags=["runtime"])


def get_db() -> Iterator[DBSession]:
    sm = get_sessionmaker()
    db = sm()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _agent_to_spec(a: Agent) -> AgentSpec:
    return AgentSpec(
        id=a.id,
        workspace_id=a.workspace_id,
        name=a.name,
        system_prompt=a.system_prompt,
        model_alias=a.model_alias,
        graph_kind=a.graph_kind,
        config=dict(a.config or {}),
        tool_ids=list(a.tool_ids or []),
        rag_collection_id=a.rag_collection_id,
    )


def _load_history(db: DBSession, session_id: UUID) -> list[dict]:
    rows = (
        db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
        .scalars()
        .all()
    )
    out: list[dict] = []
    for m in rows:
        d = {"role": m.role, "content": m.content or ""}
        if m.tool_call:
            d["tool_call"] = m.tool_call
        out.append(d)
    return out


@router.post("/run", response_model=RunResult)
async def run(
    body: dict,
    db: Annotated[DBSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RunResult:
    """Run one turn against an existing agent + session.

    Body: ``{"agent_id": "...", "session_id": "...", "user_message": "..."}``
    """

    agent = db.get(Agent, UUID(body["agent_id"]))
    if agent is None:
        raise NotFoundError("agent not found")
    session = db.get(Session, UUID(body["session_id"]))
    if session is None:
        raise NotFoundError("session not found")

    user_msg = body.get("user_message") or ""

    llm, tools, knowledge, memory = get_proxies()

    # Prefer the short-term Redis buffer if it exists; fall back to DB.
    stm = await memory.get_short_term(workspace_id=session.workspace_id, session_id=session.id)
    history = (
        [{"role": m["role"], "content": m["content"]} for m in stm]
        if stm
        else _load_history(db, session.id)
    )

    # Persist the user message first.
    db.add(
        Message(
            id=uuid4(),
            session_id=session.id,
            role="user",
            content=user_msg,
            citations=[],
            meta={},
        )
    )
    db.commit()
    await memory.append_short_term(
        workspace_id=session.workspace_id,
        session_id=session.id,
        role="user",
        content=user_msg,
    )
    publish = get_publish()
    result, events = await run_agent(
        agent=_agent_to_spec(agent),
        session_id=session.id,
        user_message=user_msg,
        history=history,
        llm=llm,
        tools=tools,
        knowledge=knowledge,
        max_iterations=settings.max_iterations,
        rag_top_k=settings.rag_default_top_k,
        publish=publish,
        opa_url=settings.opa_url,
        principal_roles=body.get("principal_roles") or ["builder"],
    )

    # Persist assistant + tool messages.
    for ev in events:
        if ev.type == "tool_call":
            db.add(
                Message(
                    id=uuid4(),
                    session_id=session.id,
                    role="assistant",
                    content=None,
                    tool_call=ev.payload,
                    meta={"event": "tool_call"},
                    citations=[],
                )
            )
        elif ev.type == "tool_result":
            db.add(
                Message(
                    id=uuid4(),
                    session_id=session.id,
                    role="tool",
                    content=json.dumps(ev.payload.get("result"))[:8000]
                    if ev.payload.get("ok")
                    else ev.payload.get("error"),
                    tool_call={"name": ev.payload.get("name"), "id": ev.payload.get("id")},
                    citations=[],
                    meta={"event": "tool_result"},
                )
            )
    if result.final_message or result.error:
        db.add(
            Message(
                id=uuid4(),
                session_id=session.id,
                role="assistant",
                content=result.final_message,
                tool_call=None,
                citations=result.citations,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                meta={"iterations": result.iterations, "error": result.error},
            )
        )
        if result.final_message:
            await memory.append_short_term(
                workspace_id=session.workspace_id,
                session_id=session.id,
                role="assistant",
                content=result.final_message,
            )
    db.commit()
    return result


@router.post("/run/stream", response_model=None, status_code=status.HTTP_200_OK)
async def run_stream(
    body: dict,
    db: Annotated[DBSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Same as ``/run`` but returns the events as SSE.

    The api-gateway uses ``/run/stream`` to flow events out to the WS client.
    """

    agent = db.get(Agent, UUID(body["agent_id"]))
    if agent is None:
        raise NotFoundError("agent not found")
    session = db.get(Session, UUID(body["session_id"]))
    if session is None:
        raise NotFoundError("session not found")

    user_msg = body.get("user_message") or ""
    llm, tools, knowledge, memory = get_proxies()
    stm = await memory.get_short_term(workspace_id=session.workspace_id, session_id=session.id)
    history = (
        [{"role": m["role"], "content": m["content"]} for m in stm]
        if stm
        else _load_history(db, session.id)
    )
    db.add(
        Message(
            id=uuid4(),
            session_id=session.id,
            role="user",
            content=user_msg,
            citations=[],
            meta={},
        )
    )
    db.commit()
    await memory.append_short_term(
        workspace_id=session.workspace_id,
        session_id=session.id,
        role="user",
        content=user_msg,
    )

    publish = get_publish()

    async def gen():
        from .graphs.react import run_react

        events: list = []
        async for ev in run_react(
            agent=_agent_to_spec(agent),
            session_id=session.id,
            user_message=user_msg,
            history=history,
            llm=llm,
            tools=tools,
            knowledge=knowledge,
            max_iterations=settings.max_iterations,
            rag_top_k=settings.rag_default_top_k,
            opa_url=settings.opa_url,
            principal_roles=body.get("principal_roles") or ["builder"],
        ):
            events.append(ev)
            if publish is not None:
                try:
                    await publish(f"chat.{ev.session_id}", ev.model_dump_json().encode())
                except Exception:
                    pass
            yield f"data: {event_to_ws(ev)}\n\n"

        # Persist messages from collected events.
        sm = get_sessionmaker()
        with sm() as s2:
            for ev in events:
                if ev.type == "tool_call":
                    s2.add(
                        Message(
                            id=uuid4(),
                            session_id=session.id,
                            role="assistant",
                            content=None,
                            tool_call=ev.payload,
                            meta={"event": "tool_call"},
                            citations=[],
                        )
                    )
                elif ev.type == "tool_result":
                    s2.add(
                        Message(
                            id=uuid4(),
                            session_id=session.id,
                            role="tool",
                            content=(
                                json.dumps(ev.payload.get("result"))[:8000]
                                if ev.payload.get("ok")
                                else ev.payload.get("error")
                            ),
                            tool_call={
                                "name": ev.payload.get("name"),
                                "id": ev.payload.get("id"),
                            },
                            citations=[],
                            meta={"event": "tool_result"},
                        )
                    )
                elif ev.type == "final":
                    final_content = ev.payload.get("content") or ""
                    s2.add(
                        Message(
                            id=uuid4(),
                            session_id=session.id,
                            role="assistant",
                            content=final_content,
                            tool_call=None,
                            citations=ev.payload.get("citations") or [],
                            tokens_in=int(ev.payload.get("tokens_in") or 0),
                            tokens_out=int(ev.payload.get("tokens_out") or 0),
                            meta={"iterations": ev.payload.get("iterations")},
                        )
                    )
                    if final_content:
                        await memory.append_short_term(
                            workspace_id=session.workspace_id,
                            session_id=session.id,
                            role="assistant",
                            content=final_content,
                        )
                elif ev.type == "error":
                    s2.add(
                        Message(
                            id=uuid4(),
                            session_id=session.id,
                            role="assistant",
                            content="",
                            tool_call=None,
                            citations=[],
                            meta={"error": ev.payload.get("message")},
                        )
                    )
            s2.commit()

        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
