"""Orchestrate a chat turn: stream events to NATS + collect a RunResult."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from agenticos_shared.logging import get_logger

from .graphs.react import run_react
from .proxies import KnowledgeProxy, LLMProxy, ToolProxy
from .schemas import AgentSpec, RunResult, StepEvent

log = get_logger(__name__)


def chat_subject(session_id: UUID) -> str:
    return f"chat.{session_id}"


async def _stream_to_nats(events: AsyncIterator[StepEvent], publish) -> AsyncIterator[StepEvent]:
    async for ev in events:
        if publish is not None:
            try:
                await publish(chat_subject(ev.session_id), ev.model_dump_json().encode("utf-8"))
            except Exception:
                pass
        yield ev


async def run_agent(
    *,
    agent: AgentSpec,
    session_id: UUID,
    user_message: str,
    history: list[dict[str, Any]],
    llm: LLMProxy,
    tools: ToolProxy,
    knowledge: KnowledgeProxy,
    max_iterations: int = 6,
    rag_top_k: int = 5,
    publish: Any | None = None,
    opa_url: str | None = None,
    principal_roles: list[str] | None = None,
) -> tuple[RunResult, list[StepEvent]]:
    """Execute one chat turn and collect the final RunResult.

    ``publish`` is an optional async callable ``(subject, bytes) -> None``;
    typically a NATS publish bound by the runner.
    """

    if agent.graph_kind != "react":
        raise ValueError(f"unknown graph_kind: {agent.graph_kind}")

    events_collected: list[StepEvent] = []
    final_text = ""
    iterations = 0
    tokens_in = 0
    tokens_out = 0
    citations: list[dict[str, Any]] = []
    tool_calls_seen: list[dict[str, Any]] = []
    tool_results_seen: list[dict[str, Any]] = []
    error: str | None = None

    gen = run_react(
        agent=agent,
        session_id=session_id,
        user_message=user_message,
        history=history,
        llm=llm,
        tools=tools,
        knowledge=knowledge,
        max_iterations=max_iterations,
        rag_top_k=rag_top_k,
        opa_url=opa_url,
        principal_roles=principal_roles,
    )

    async for ev in _stream_to_nats(gen, publish):
        events_collected.append(ev)
        p = ev.payload
        if ev.type == "tool_call":
            tool_calls_seen.append(p)
        elif ev.type == "tool_result":
            tool_results_seen.append(p)
        elif ev.type == "citations":
            citations = list(p.get("hits") or [])
        elif ev.type == "final":
            final_text = p.get("content") or ""
            iterations = int(p.get("iterations") or 0)
            tokens_in = int(p.get("tokens_in") or 0)
            tokens_out = int(p.get("tokens_out") or 0)
            citations = list(p.get("citations") or citations)
        elif ev.type == "error":
            error = p.get("message")

    return (
        RunResult(
            final_message=final_text,
            tool_calls=tool_calls_seen,
            tool_results=tool_results_seen,
            citations=citations,
            iterations=iterations,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error,
        ),
        events_collected,
    )


def event_to_ws(ev: StepEvent) -> str:
    """Serialise a StepEvent for the WS client."""

    return json.dumps({"type": ev.type, "session_id": str(ev.session_id), "payload": ev.payload})
