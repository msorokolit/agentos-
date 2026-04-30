"""Long-term memory: ``memory_item`` rows + optional vector search.

* ``put_item`` upserts by ``(workspace_id, scope, owner_id, key)``.
* ``search`` finds top-K items by cosine similarity (in Python on SQLite,
  pgvector on PostgreSQL).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from agenticos_shared.errors import NotFoundError
from agenticos_shared.models import MemoryItem
from sqlalchemy import select
from sqlalchemy.orm import Session


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def upsert_item(
    db: Session,
    *,
    workspace_id: UUID,
    scope: str,
    owner_id: UUID | None,
    key: str,
    value: dict[str, Any],
    summary: str | None,
    embedding: list[float] | None = None,
    ttl_seconds: int | None = None,
) -> MemoryItem:
    q = select(MemoryItem).where(
        MemoryItem.workspace_id == workspace_id,
        MemoryItem.scope == scope,
        MemoryItem.owner_id == owner_id,
        MemoryItem.key == key,
    )
    row = db.execute(q).scalar_one_or_none()
    now = datetime.now(tz=UTC)
    expires_at = (now + timedelta(seconds=ttl_seconds)) if ttl_seconds else None

    if row is None:
        row = MemoryItem(
            id=uuid4(),
            workspace_id=workspace_id,
            scope=scope,
            owner_id=owner_id,
            key=key,
            value=value,
            summary=summary,
            embedding=embedding,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.value = value
        row.summary = summary
        if embedding is not None:
            row.embedding = embedding
        row.expires_at = expires_at
        row.updated_at = now
    db.flush()
    return row


def get_item(db: Session, *, item_id: UUID) -> MemoryItem:
    row = db.get(MemoryItem, item_id)
    if row is None:
        raise NotFoundError("memory item not found")
    return row


def list_items(
    db: Session,
    *,
    workspace_id: UUID,
    scope: str | None = None,
    owner_id: UUID | None = None,
    key: str | None = None,
    limit: int = 50,
) -> list[MemoryItem]:
    q = select(MemoryItem).where(MemoryItem.workspace_id == workspace_id)
    if scope is not None:
        q = q.where(MemoryItem.scope == scope)
    if owner_id is not None:
        q = q.where(MemoryItem.owner_id == owner_id)
    if key is not None:
        q = q.where(MemoryItem.key == key)
    q = q.order_by(MemoryItem.updated_at.desc()).limit(limit)
    return list(db.execute(q).scalars().all())


def delete_item(db: Session, *, item_id: UUID) -> None:
    row = db.get(MemoryItem, item_id)
    if row is None:
        raise NotFoundError("memory item not found")
    db.delete(row)


def search_by_embedding(
    db: Session,
    *,
    workspace_id: UUID,
    query_embedding: list[float],
    scope: str | None = None,
    owner_id: UUID | None = None,
    top_k: int = 5,
) -> list[tuple[MemoryItem, float]]:
    is_pg = db.bind.dialect.name == "postgresql"
    if is_pg:
        from sqlalchemy import text as sql_text

        sql = sql_text(
            """
            SELECT id, embedding <=> CAST(:emb AS vector) AS distance
            FROM memory_item
            WHERE workspace_id = :ws
              AND embedding IS NOT NULL
              AND (CAST(:scope AS text) IS NULL OR scope = CAST(:scope AS text))
              AND (CAST(:owner AS uuid) IS NULL OR owner_id = CAST(:owner AS uuid))
            ORDER BY embedding <=> CAST(:emb AS vector)
            LIMIT :k
            """
        )
        rows = db.execute(
            sql,
            {
                "ws": workspace_id,
                "emb": query_embedding,
                "scope": scope,
                "owner": owner_id,
                "k": top_k,
            },
        ).all()
        out: list[tuple[MemoryItem, float]] = []
        for r in rows:
            item = db.get(MemoryItem, r.id)
            if item is not None:
                out.append((item, 1.0 - float(r.distance)))
        return out

    # Python fallback (SQLite, etc.)
    candidates = list_items(
        db,
        workspace_id=workspace_id,
        scope=scope,
        owner_id=owner_id,
        limit=10_000,
    )
    scored = [
        (it, _cosine(it.embedding or [], query_embedding)) for it in candidates if it.embedding
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
