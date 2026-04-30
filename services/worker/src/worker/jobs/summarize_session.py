"""Summarize a finished session and persist as a long-term memory item.

Triggered when the api-gateway closes a session (sets ``session.ended_at``).
The summarizer:

1. Loads the session's messages.
2. Calls llm-gateway ``/v1/chat/completions`` with a short instruction
   prompt to produce a 3-5 sentence recap.
3. Writes the recap to memory-svc as a workspace-scoped ``memory_item``
   with ``embed=true`` so future agents can retrieve it.

If any step fails the job logs and exits cleanly — we'd rather miss a
summary than poison the queue.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from agenticos_shared.db import get_sessionmaker
from agenticos_shared.logging import get_logger
from agenticos_shared.models import Message
from agenticos_shared.models import Session as SessionRow
from sqlalchemy import select

from ..settings import get_settings

log = get_logger(__name__)


_SUMMARY_PROMPT = (
    "Summarize the following chat in 3-5 short sentences. Capture the user's "
    "intent, the agent's final answer, and any decisions made. Do not invent "
    "facts. Output plain text only."
)


def _gather_transcript(messages: list[Message], *, limit_chars: int = 6000) -> str:
    parts: list[str] = []
    used = 0
    for m in messages:
        if not m.content:
            continue
        line = f"{m.role.upper()}: {m.content.strip()}"
        if used + len(line) > limit_chars:
            line = line[: max(0, limit_chars - used)]
            parts.append(line)
            break
        parts.append(line)
        used += len(line) + 1
    return "\n".join(parts)


async def _llm_chat(
    *,
    gateway_url: str,
    model_alias: str,
    transcript: str,
    timeout: float,
) -> str | None:
    body: dict[str, Any] = {
        "model": model_alias,
        "messages": [
            {"role": "system", "content": _SUMMARY_PROMPT},
            {"role": "user", "content": transcript},
        ],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{gateway_url.rstrip('/')}/v1/chat/completions", json=body)
    except httpx.HTTPError as exc:
        log.warning("summarize_chat_transport_error", error=str(exc))
        return None
    if r.status_code >= 400:
        log.warning("summarize_chat_failed", status=r.status_code, body=r.text[:300])
        return None
    data = r.json()
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content")


async def _put_memory(
    *,
    memory_url: str,
    workspace_id: UUID,
    session_id: UUID,
    summary: str,
    embed_alias: str,
    timeout: float,
) -> bool:
    payload: dict[str, Any] = {
        "workspace_id": str(workspace_id),
        "scope": "session",
        "owner_id": str(session_id),
        "key": f"summary:{session_id}",
        "value": {"session_id": str(session_id)},
        "summary": summary,
        "embed": True,
        "embed_alias": embed_alias,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{memory_url.rstrip('/')}/items", json=payload)
    except httpx.HTTPError as exc:
        log.warning("summarize_memory_transport_error", error=str(exc))
        return False
    if r.status_code >= 400:
        log.warning("summarize_memory_put_failed", status=r.status_code, body=r.text[:300])
        return False
    return True


async def summarize_session(
    ctx: dict[str, Any],
    session_id: str,
    *,
    chat_alias: str | None = None,
    embed_alias: str | None = None,
) -> dict[str, Any]:
    """arq job: summarise a single session.

    Returns ``{"ok": bool, "summary": str|None, "reason": str|None}``.
    Idempotent: if a summary already exists for the session, no-ops.
    """

    settings = get_settings()
    sid = UUID(session_id)
    sm = get_sessionmaker()
    with sm() as db:
        sess = db.get(SessionRow, sid)
        if sess is None:
            return {"ok": False, "reason": "session not found"}
        msgs = (
            db.execute(
                select(Message).where(Message.session_id == sid).order_by(Message.created_at)
            )
            .scalars()
            .all()
        )
    if not msgs:
        return {"ok": False, "reason": "empty session"}

    transcript = _gather_transcript(list(msgs))
    if not transcript.strip():
        return {"ok": False, "reason": "no content"}

    summary = await _llm_chat(
        gateway_url=settings.llm_gateway_url,
        model_alias=chat_alias or settings.default_chat_model_alias,
        transcript=transcript,
        timeout=120.0,
    )
    if not summary:
        return {"ok": False, "reason": "llm failed"}

    ok = await _put_memory(
        memory_url=settings.memory_svc_url,
        workspace_id=sess.workspace_id,
        session_id=sid,
        summary=summary,
        embed_alias=embed_alias or settings.default_embed_model_alias,
        timeout=60.0,
    )
    return {"ok": ok, "summary": summary if ok else None}
