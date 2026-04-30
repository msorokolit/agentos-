"""OpenInference semantic conventions for LLM + tool spans.

Reference: https://github.com/Arize-ai/openinference/tree/main/spec

We deliberately keep this lightweight rather than depending on the
``openinference-semantic-conventions`` package — the constants don't
churn often and we want zero new runtime deps. ``record_*`` helpers
attach attributes to the **current** active OTel span, so callers that
ignore tracing don't pay any cost.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from opentelemetry import trace

# ---- Span kind / category ----
OPENINFERENCE_SPAN_KIND = "openinference.span.kind"
SPAN_KIND_LLM = "LLM"
SPAN_KIND_CHAIN = "CHAIN"
SPAN_KIND_TOOL = "TOOL"
SPAN_KIND_RETRIEVER = "RETRIEVER"
SPAN_KIND_EMBEDDING = "EMBEDDING"
SPAN_KIND_AGENT = "AGENT"

# ---- LLM ----
LLM_PROVIDER = "llm.provider"
LLM_MODEL_NAME = "llm.model_name"
LLM_INVOCATION_PARAMETERS = "llm.invocation_parameters"
LLM_TOKEN_COUNT_PROMPT = "llm.token_count.prompt"
LLM_TOKEN_COUNT_COMPLETION = "llm.token_count.completion"
LLM_TOKEN_COUNT_TOTAL = "llm.token_count.total"
LLM_INPUT_MESSAGES = "llm.input_messages"
LLM_OUTPUT_MESSAGES = "llm.output_messages"

# ---- Tools ----
TOOL_NAME = "tool.name"
TOOL_DESCRIPTION = "tool.description"
TOOL_PARAMETERS = "tool.parameters"
TOOL_INPUT = "input.value"
TOOL_OUTPUT = "output.value"

# ---- Embeddings + retrieval ----
EMBEDDING_MODEL_NAME = "embedding.model_name"
EMBEDDING_TEXT = "embedding.text"
RETRIEVAL_DOCUMENTS = "retrieval.documents"

# ---- Agents ----
AGENT_NAME = "agent.name"
SESSION_ID = "session.id"
USER_ID = "user.id"
WORKSPACE_ID = "workspace.id"


def _truncate(value: str, *, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"


def _safe_json(value: Any, *, limit: int = 4096) -> str:
    try:
        return _truncate(json.dumps(value, default=str), limit=limit)
    except Exception:
        return _truncate(repr(value), limit=limit)


def _set(attrs: dict[str, Any]) -> None:
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return
    for k, v in attrs.items():
        if v is None:
            continue
        try:
            span.set_attribute(k, v)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def annotate_llm_call(
    *,
    provider: str,
    model: str,
    alias: str,
    kind: str,
    invocation_parameters: dict[str, Any] | None = None,
    input_messages: Iterable[dict[str, Any]] | None = None,
    output_text: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    workspace_id: str | None = None,
) -> None:
    attrs: dict[str, Any] = {
        OPENINFERENCE_SPAN_KIND: SPAN_KIND_LLM if kind == "chat" else SPAN_KIND_EMBEDDING,
        LLM_PROVIDER: provider,
        LLM_MODEL_NAME: model,
        "llm.alias": alias,
        LLM_TOKEN_COUNT_PROMPT: prompt_tokens,
        LLM_TOKEN_COUNT_COMPLETION: completion_tokens,
        LLM_TOKEN_COUNT_TOTAL: prompt_tokens + completion_tokens,
        WORKSPACE_ID: workspace_id,
    }
    if invocation_parameters:
        attrs[LLM_INVOCATION_PARAMETERS] = _safe_json(invocation_parameters)
    if input_messages is not None:
        attrs[LLM_INPUT_MESSAGES] = _safe_json(list(input_messages))
    if output_text is not None:
        attrs[LLM_OUTPUT_MESSAGES] = _truncate(output_text)
    _set(attrs)


def annotate_tool_call(
    *,
    tool_name: str,
    tool_kind: str,
    args: dict[str, Any] | None = None,
    result: Any = None,
    ok: bool = True,
    description: str | None = None,
) -> None:
    attrs: dict[str, Any] = {
        OPENINFERENCE_SPAN_KIND: SPAN_KIND_TOOL,
        TOOL_NAME: tool_name,
        "tool.kind": tool_kind,
        "tool.ok": ok,
    }
    if description:
        attrs[TOOL_DESCRIPTION] = description
    if args is not None:
        attrs[TOOL_INPUT] = _safe_json(args)
    if result is not None and ok:
        attrs[TOOL_OUTPUT] = _safe_json(result)
    _set(attrs)


def annotate_agent_run(
    *,
    agent_name: str,
    session_id: str,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> None:
    _set(
        {
            OPENINFERENCE_SPAN_KIND: SPAN_KIND_AGENT,
            AGENT_NAME: agent_name,
            SESSION_ID: session_id,
            USER_ID: user_id,
            WORKSPACE_ID: workspace_id,
        }
    )


def annotate_retrieval(
    *,
    query: str,
    documents: Iterable[dict[str, Any]] | None = None,
    workspace_id: str | None = None,
) -> None:
    docs = list(documents or [])
    _set(
        {
            OPENINFERENCE_SPAN_KIND: SPAN_KIND_RETRIEVER,
            "input.value": _truncate(query),
            RETRIEVAL_DOCUMENTS: _safe_json(docs),
            "retrieval.documents.count": len(docs),
            WORKSPACE_ID: workspace_id,
        }
    )
