"""OpenAI-compatible chat + embeddings endpoints.

Routing: ``model`` field in the request body is the **alias** registered
in this gateway, not the upstream model name.
"""

from __future__ import annotations

import json
import time
from typing import Annotated

from agenticos_shared.errors import ValidationError
from agenticos_shared.logging import get_logger
from agenticos_shared.metrics import record_llm_call
from agenticos_shared.models import TokenUsage
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import registry
from ..providers import make_provider
from ..quota import QuotaService
from ..schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)
from ..state import get_quota
from .deps import get_db

router = APIRouter(prefix="/v1", tags=["llm"])
log = get_logger(__name__)


def _record_usage(
    db: Session,
    *,
    workspace_id,
    actor_id,
    request_id,
    model_alias: str,
    provider: str,
    kind: str,
    prompt: int,
    completion: int,
    latency_ms: int,
) -> None:
    db.add(
        TokenUsage(
            workspace_id=workspace_id,
            actor_id=actor_id,
            request_id=request_id,
            model_alias=model_alias,
            provider=provider,
            kind=kind,
            prompt_tokens=prompt,
            completion_tokens=completion,
            latency_ms=latency_ms,
        )
    )
    db.commit()


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    quota: Annotated[QuotaService, Depends(get_quota)],
):
    rm = await registry.resolve(body.model)
    if rm.kind != "chat":
        raise ValidationError(f"model alias '{body.model}' is not a chat model")

    await quota.check_and_reserve_request(body.workspace_id)

    # Merge default_params with request (request overrides).
    merged = {**rm.default_params, **body.model_dump(exclude_none=True)}
    merged["messages"] = [m.model_dump(exclude_none=True) for m in body.messages]
    merged["model"] = rm.model_name  # provider call uses upstream model name

    provider_obj = make_provider(rm.provider, endpoint=rm.endpoint, model_name=rm.model_name)
    request_id = request.headers.get("x-request-id")

    if not body.stream:
        t0 = time.monotonic()
        upstream = await provider_obj.chat(merged)
        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = upstream.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        await quota.add_tokens(
            body.workspace_id,
            prompt=prompt_tokens,
            completion=completion_tokens,
        )
        _record_usage(
            db,
            workspace_id=body.workspace_id,
            actor_id=None,
            request_id=request_id,
            model_alias=rm.alias,
            provider=rm.provider,
            kind="chat",
            prompt=prompt_tokens,
            completion=completion_tokens,
            latency_ms=latency_ms,
        )
        record_llm_call(
            provider=rm.provider,
            alias=rm.alias,
            model=rm.model_name,
            kind="chat",
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            workspace_id=str(body.workspace_id) if body.workspace_id else None,
        )
        # Always echo back the *alias* — what the caller asked for.
        upstream["model"] = rm.alias
        return ChatCompletionResponse.model_validate(upstream)

    # Streaming path → SSE
    async def gen():
        prompt_total = 0
        completion_total = 0
        t0 = time.monotonic()
        async for chunk in provider_obj.chat_stream(merged):
            chunk["model"] = rm.alias
            # Crude usage estimation per chunk for streaming providers.
            for ch in chunk.get("choices", []):
                content = (ch.get("delta") or {}).get("content")
                if content:
                    completion_total += max(1, len(content) // 4)
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"
        latency_ms = int((time.monotonic() - t0) * 1000)
        await quota.add_tokens(body.workspace_id, prompt=prompt_total, completion=completion_total)
        try:
            _record_usage(
                db,
                workspace_id=body.workspace_id,
                actor_id=None,
                request_id=request_id,
                model_alias=rm.alias,
                provider=rm.provider,
                kind="chat",
                prompt=prompt_total,
                completion=completion_total,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            log.warning("token_usage_record_failed", error=str(exc))

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/embeddings", response_model=EmbeddingResponse)
async def embeddings(
    body: EmbeddingRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    quota: Annotated[QuotaService, Depends(get_quota)],
):
    rm = await registry.resolve(body.model)
    if rm.kind != "embedding":
        raise ValidationError(f"model alias '{body.model}' is not an embedding model")

    await quota.check_and_reserve_request(body.workspace_id)
    provider_obj = make_provider(rm.provider, endpoint=rm.endpoint, model_name=rm.model_name)
    t0 = time.monotonic()
    upstream = await provider_obj.embed(body.model_dump(exclude_none=True))
    latency_ms = int((time.monotonic() - t0) * 1000)
    upstream["model"] = rm.alias
    usage = upstream.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    await quota.add_tokens(body.workspace_id, prompt=prompt_tokens, completion=0)
    _record_usage(
        db,
        workspace_id=body.workspace_id,
        actor_id=None,
        request_id=request.headers.get("x-request-id"),
        model_alias=rm.alias,
        provider=rm.provider,
        kind="embedding",
        prompt=prompt_tokens,
        completion=0,
        latency_ms=latency_ms,
    )
    record_llm_call(
        provider=rm.provider,
        alias=rm.alias,
        model=rm.model_name,
        kind="embedding",
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=0,
        workspace_id=str(body.workspace_id) if body.workspace_id else None,
    )
    return EmbeddingResponse.model_validate(upstream)
