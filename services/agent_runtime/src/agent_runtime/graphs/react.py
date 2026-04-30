"""ReAct graph: prepare → plan → policy → act → observe → finalize.

Implemented as a small async generator state machine without LangGraph.
This keeps the dependency surface small and lets us mock cleanly in tests.

The graph drives an LLM with function-calling. After the model emits an
``assistant`` message:

* If it has ``tool_calls`` we invoke each, append tool messages, and loop.
* Otherwise we emit a ``final`` event and stop.

Up to ``max_iterations`` loops are permitted.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from agenticos_shared.logging import get_logger

from ..proxies import KnowledgeProxy, LLMProxy, ToolProxy
from ..schemas import AgentSpec, StepEvent

log = get_logger(__name__)


def _prepare_messages(
    *,
    agent: AgentSpec,
    user_message: str,
    history: list[dict[str, Any]],
    rag_context: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    if agent.system_prompt:
        msgs.append({"role": "system", "content": agent.system_prompt})
    if rag_context:
        ctx = "\n\n".join(
            f"[{i + 1}] {h['document_title']} (chunk #{h['ord']}):\n{h['text']}"
            for i, h in enumerate(rag_context)
        )
        msgs.append(
            {
                "role": "system",
                "content": (
                    "You have access to the following retrieved context. "
                    "Cite sources by their bracket number when you use them.\n\n" + ctx
                ),
            }
        )
    msgs.extend(history)
    msgs.append({"role": "user", "content": user_message})
    return msgs


def _tools_payload(tool_descriptors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tool_descriptors:
        desc = t.get("descriptor") or {}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": (t.get("description") or desc.get("description") or ""),
                    "parameters": desc.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return out


async def run_react(
    *,
    agent: AgentSpec,
    session_id,  # UUID — kept untyped for simpler tests
    user_message: str,
    history: list[dict[str, Any]],
    llm: LLMProxy,
    tools: ToolProxy,
    knowledge: KnowledgeProxy,
    max_iterations: int = 6,
    rag_top_k: int = 5,
) -> AsyncIterator[StepEvent]:
    """Async generator yielding StepEvents for an agent turn."""

    # ---- prepare: optional RAG ----
    rag_hits: list[dict[str, Any]] = []
    if agent.rag_collection_id is not None or agent.config.get("rag_enabled"):
        knowledge_resp = await knowledge.search(
            workspace_id=agent.workspace_id,
            query=user_message,
            top_k=rag_top_k,
            collection_id=agent.rag_collection_id,
        )
        rag_hits = knowledge_resp.get("hits") or []
        if rag_hits:
            yield StepEvent(
                type="citations",
                session_id=session_id,
                payload={"hits": rag_hits},
            )

    yield StepEvent(type="step", session_id=session_id, payload={"node": "plan"})

    # Resolve registered tools (workspace + global).
    tool_descriptors: list[dict[str, Any]] = []
    if agent.tool_ids:
        all_tools = await tools.list_for(agent.workspace_id)
        wanted = set(agent.tool_ids)
        tool_descriptors = [t for t in all_tools if t["id"] in wanted and t.get("enabled", True)]

    messages = _prepare_messages(
        agent=agent,
        user_message=user_message,
        history=history,
        rag_context=rag_hits,
    )
    tool_choice: str | None = "auto" if tool_descriptors else None

    iterations = 0
    final_text = ""
    total_in = 0
    total_out = 0

    while iterations < max_iterations:
        iterations += 1
        chat_payload: dict[str, Any] = {
            "model": agent.model_alias,
            "messages": messages,
            "stream": False,
        }
        if tool_descriptors:
            chat_payload["tools"] = _tools_payload(tool_descriptors)
            if tool_choice:
                chat_payload["tool_choice"] = tool_choice
        # Allow agent.config to override sampling.
        for k in ("temperature", "top_p", "max_tokens", "response_format"):
            if k in agent.config:
                chat_payload[k] = agent.config[k]

        try:
            resp = await llm.chat(chat_payload)
        except Exception as exc:
            yield StepEvent(
                type="error",
                session_id=session_id,
                payload={"message": str(exc)[:500], "iteration": iterations},
            )
            return

        usage = resp.get("usage") or {}
        total_in += int(usage.get("prompt_tokens", 0) or 0)
        total_out += int(usage.get("completion_tokens", 0) or 0)

        choices = resp.get("choices") or []
        if not choices:
            yield StepEvent(
                type="error",
                session_id=session_id,
                payload={"message": "no choices returned"},
            )
            return

        msg = choices[0].get("message") or {}
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            final_text = msg.get("content") or ""
            yield StepEvent(
                type="delta",
                session_id=session_id,
                payload={"content": final_text},
            )
            yield StepEvent(
                type="final",
                session_id=session_id,
                payload={
                    "content": final_text,
                    "iterations": iterations,
                    "tokens_in": total_in,
                    "tokens_out": total_out,
                    "citations": rag_hits,
                },
            )
            return

        # Append the assistant message *with* tool_calls so the model sees them next round.
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": tool_calls,
        }
        messages.append(assistant_msg)

        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args_raw = fn.get("arguments") or "{}"
            try:
                args = args_raw if isinstance(args_raw, dict) else json.loads(args_raw)
            except json.JSONDecodeError:
                args = {}

            yield StepEvent(
                type="tool_call",
                session_id=session_id,
                payload={"id": call.get("id"), "name": name, "args": args},
            )

            tool_result = await tools.invoke(
                tool_id=None,
                name=name,
                workspace_id=agent.workspace_id,
                args=args,
            )
            yield StepEvent(
                type="tool_result",
                session_id=session_id,
                payload={
                    "id": call.get("id"),
                    "name": name,
                    "ok": bool(tool_result.get("ok", False)),
                    "result": tool_result.get("result"),
                    "error": tool_result.get("error"),
                },
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": name,
                    "content": json.dumps(
                        tool_result.get("result")
                        if tool_result.get("ok")
                        else {"error": tool_result.get("error", "tool failed")}
                    )[:8000],
                }
            )

    yield StepEvent(
        type="error",
        session_id=session_id,
        payload={"message": f"hit max_iterations={max_iterations}"},
    )
