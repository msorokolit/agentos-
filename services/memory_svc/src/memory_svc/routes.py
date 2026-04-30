"""HTTP API for the memory service.

This is an internal service; the api-gateway (and agent-runtime) call it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from agenticos_shared.db import get_sessionmaker
from agenticos_shared.models import MemoryItem
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from . import long_term
from .embedder import embed_one
from .schemas import (
    MemoryItemOut,
    MemoryPut,
    MemoryQuery,
    ShortTermAppend,
    ShortTermItem,
    ShortTermResponse,
)
from .settings import Settings, get_settings
from .state import get_short_term

router = APIRouter(tags=["memory"])


def get_db() -> Iterator[Session]:
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


def _to_out(row: MemoryItem) -> MemoryItemOut:
    return MemoryItemOut(
        id=row.id,
        workspace_id=row.workspace_id,
        scope=row.scope,  # type: ignore[arg-type]
        owner_id=row.owner_id,
        key=row.key,
        value=dict(row.value or {}),
        summary=row.summary,
        has_embedding=bool(row.embedding),
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Short-term (Redis)
# ---------------------------------------------------------------------------
@router.post("/short-term/append", response_model=ShortTermResponse)
def st_append(body: ShortTermAppend) -> ShortTermResponse:
    stm = get_short_term()
    stm.append(
        workspace_id=body.workspace_id,
        session_id=body.session_id,
        role=body.role,
        content=body.content,
        max_messages=body.max_messages,
    )
    items = stm.get(workspace_id=body.workspace_id, session_id=body.session_id)
    return ShortTermResponse(
        session_id=body.session_id,
        messages=[ShortTermItem(**i) for i in items],
    )


@router.get("/short-term/{workspace_id}/{session_id}", response_model=ShortTermResponse)
def st_get(workspace_id: UUID, session_id: UUID) -> ShortTermResponse:
    items = get_short_term().get(workspace_id=workspace_id, session_id=session_id)
    return ShortTermResponse(
        session_id=session_id,
        messages=[ShortTermItem(**i) for i in items],
    )


@router.delete(
    "/short-term/{workspace_id}/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def st_clear(workspace_id: UUID, session_id: UUID) -> None:
    get_short_term().clear(workspace_id=workspace_id, session_id=session_id)


# ---------------------------------------------------------------------------
# Long-term (Postgres + pgvector)
# ---------------------------------------------------------------------------
@router.post("/put", response_model=MemoryItemOut, status_code=status.HTTP_201_CREATED)
async def put_alias(
    body: MemoryPut,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MemoryItemOut:
    """Alias of ``/items`` matching PLAN §4 internal verb ``POST /memory/put``."""

    return await put_item(body, db, settings)


class MemoryGet(MemoryQuery):
    """Body for ``POST /get`` — same shape as ``/search``."""


@router.post("/get", response_model=list[MemoryItemOut])
async def get_alias(
    body: MemoryGet,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[MemoryItemOut]:
    """Alias of ``/search`` matching PLAN §4 internal verb ``POST /memory/get``."""

    return await search(body, db, settings)


@router.post("/items", response_model=MemoryItemOut, status_code=status.HTTP_201_CREATED)
async def put_item(
    body: MemoryPut,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MemoryItemOut:
    embedding: list[float] | None = None
    if body.embed:
        text = body.summary or " ".join(str(v) for v in body.value.values())[:4096]
        embedding = await embed_one(
            gateway_url=settings.llm_gateway_url,
            model_alias=body.embed_alias or settings.default_embed_model_alias,
            text=text,
        )

    row = long_term.upsert_item(
        db,
        workspace_id=body.workspace_id,
        scope=body.scope,
        owner_id=body.owner_id,
        key=body.key,
        value=body.value,
        summary=body.summary,
        embedding=embedding,
        ttl_seconds=body.ttl_seconds,
    )
    return _to_out(row)


@router.get("/items", response_model=list[MemoryItemOut])
def list_items(
    db: Annotated[Session, Depends(get_db)],
    workspace_id: UUID,
    scope: str | None = None,
    owner_id: UUID | None = None,
    key: str | None = None,
    limit: int = 50,
) -> list[MemoryItemOut]:
    rows = long_term.list_items(
        db,
        workspace_id=workspace_id,
        scope=scope,
        owner_id=owner_id,
        key=key,
        limit=limit,
    )
    return [_to_out(r) for r in rows]


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: UUID, db: Annotated[Session, Depends(get_db)]) -> None:
    long_term.delete_item(db, item_id=item_id)


@router.post("/search", response_model=list[MemoryItemOut])
async def search(
    body: MemoryQuery,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[MemoryItemOut]:
    if not body.query:
        # Plain listing path.
        rows = long_term.list_items(
            db,
            workspace_id=body.workspace_id,
            scope=body.scope,
            owner_id=body.owner_id,
            key=body.key,
            limit=body.top_k,
        )
        return [_to_out(r) for r in rows]

    embedding = await embed_one(
        gateway_url=settings.llm_gateway_url,
        model_alias=body.embed_alias or settings.default_embed_model_alias,
        text=body.query,
    )
    if embedding is None:
        return []

    pairs = long_term.search_by_embedding(
        db,
        workspace_id=body.workspace_id,
        query_embedding=embedding,
        scope=body.scope,
        owner_id=body.owner_id,
        top_k=body.top_k,
    )
    return [_to_out(it) for it, _score in pairs]
