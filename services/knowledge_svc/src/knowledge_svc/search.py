"""Hybrid (vector + keyword) search.

* On **PostgreSQL** with pgvector + a generated ``tsv`` column, we run a
  combined query and merge by reciprocal-rank-fusion (RRF).
* On other dialects (SQLite in tests), we fall back to in-Python cosine
  similarity over ``Chunk.embedding`` JSON columns plus a simple LIKE
  scan, then RRF.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from agenticos_shared.models import Chunk, Document
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass
class Hit:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    ord: int
    text: str
    score: float
    meta: dict


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _rrf(rankings: list[list[UUID]], *, k: int = 60) -> dict[UUID, float]:
    """Reciprocal rank fusion across multiple ranked lists."""

    out: dict[UUID, float] = {}
    for ranking in rankings:
        for pos, cid in enumerate(ranking, start=1):
            out[cid] = out.get(cid, 0.0) + 1.0 / (k + pos)
    return out


def hybrid_search(
    db: Session,
    *,
    workspace_id: UUID,
    query: str,
    query_embedding: list[float] | None,
    collection_id: UUID | None = None,
    top_k: int = 8,
) -> list[Hit]:
    """Run hybrid retrieval over chunks in ``workspace_id``."""

    is_pg = db.bind.dialect.name == "postgresql"

    if is_pg and query_embedding is not None:
        return _pg_hybrid(
            db,
            workspace_id=workspace_id,
            query=query,
            query_embedding=query_embedding,
            collection_id=collection_id,
            top_k=top_k,
        )
    return _python_hybrid(
        db,
        workspace_id=workspace_id,
        query=query,
        query_embedding=query_embedding,
        collection_id=collection_id,
        top_k=top_k,
    )


def _python_hybrid(
    db: Session,
    *,
    workspace_id: UUID,
    query: str,
    query_embedding: list[float] | None,
    collection_id: UUID | None,
    top_k: int,
) -> list[Hit]:
    # Fetch candidate chunks (LIKE first, then add all chunks if too few).
    q = (
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.workspace_id == workspace_id)
    )
    if collection_id is not None:
        from agenticos_shared.models import CollectionDocument

        q = q.where(
            (Document.collection_id == collection_id)
            | Document.id.in_(
                select(CollectionDocument.document_id).where(
                    CollectionDocument.collection_id == collection_id
                )
            )
        )

    rows = db.execute(q).all()

    # Keyword scoring: count case-insensitive token hits.
    tokens = [t.lower() for t in query.split() if t]

    def kw_score(text: str) -> float:
        if not tokens:
            return 0.0
        lower = text.lower()
        return sum(lower.count(t) for t in tokens)

    keyword_ranked: list[tuple[Chunk, Document, float]] = sorted(
        ((c, d, kw_score(c.text)) for c, d in rows),
        key=lambda x: x[2],
        reverse=True,
    )
    keyword_ids = [c.id for c, _, score in keyword_ranked if score > 0]

    vector_ids: list[UUID] = []
    if query_embedding is not None:
        scored: list[tuple[Chunk, Document, float]] = []
        for c, d in rows:
            emb = c.embedding
            if not emb:
                continue
            scored.append((c, d, _cosine(emb, query_embedding)))
        scored.sort(key=lambda x: x[2], reverse=True)
        vector_ids = [c.id for c, _, _ in scored if _ > 0]

    fused = _rrf([vector_ids, keyword_ids])
    if not fused:
        return []

    by_id = {c.id: (c, d) for c, d in rows}
    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]

    out: list[Hit] = []
    for cid, score in ordered:
        if cid not in by_id:
            continue
        c, d = by_id[cid]
        out.append(
            Hit(
                chunk_id=c.id,
                document_id=d.id,
                document_title=d.title,
                ord=c.ord,
                text=c.text,
                score=float(score),
                meta=dict(c.meta or {}),
            )
        )
    return out


def _pg_hybrid(
    db: Session,
    *,
    workspace_id: UUID,
    query: str,
    query_embedding: list[float],
    collection_id: UUID | None,
    top_k: int,
) -> list[Hit]:
    from sqlalchemy import text as sql_text

    # ``cd`` is the new many-to-many join; we LEFT JOIN it and accept
    # either the legacy primary collection_id OR a row in the join table.
    cd_filter = (
        "(CAST(:col AS uuid) IS NULL "
        "OR d.collection_id = CAST(:col AS uuid) "
        "OR EXISTS (SELECT 1 FROM collection_document cd "
        "           WHERE cd.document_id = d.id AND cd.collection_id = CAST(:col AS uuid)))"
    )
    # ``cd_filter`` is a fixed string literal built above so these
    # f-strings are not a SQL-injection surface.
    vec_query = f"""
        SELECT c.id AS chunk_id, c.document_id, d.title AS doc_title,
               c.ord, c.text, c.embedding <=> CAST(:emb AS vector) AS distance, c.meta
        FROM chunk c JOIN document d ON d.id = c.document_id
        WHERE c.workspace_id = :ws
          AND {cd_filter}
        ORDER BY c.embedding <=> CAST(:emb AS vector)
        LIMIT :k
        """  # noqa: S608
    vec_sql = sql_text(vec_query)
    kw_query = f"""
        SELECT c.id AS chunk_id, c.document_id, d.title AS doc_title,
               c.ord, c.text, ts_rank_cd(c.tsv, plainto_tsquery('simple', :q)) AS rank, c.meta
        FROM chunk c JOIN document d ON d.id = c.document_id
        WHERE c.workspace_id = :ws
          AND c.tsv @@ plainto_tsquery('simple', :q)
          AND {cd_filter}
        ORDER BY rank DESC
        LIMIT :k
        """  # noqa: S608
    kw_sql = sql_text(kw_query)
    params = {
        "ws": workspace_id,
        "col": collection_id,
        "emb": query_embedding,
        "q": query,
        "k": top_k * 2,
    }
    vec_rows = db.execute(vec_sql, params).all()
    kw_rows = db.execute(kw_sql, params).all()

    vec_ids = [r.chunk_id for r in vec_rows]
    kw_ids = [r.chunk_id for r in kw_rows]
    fused = _rrf([vec_ids, kw_ids])

    by_id = {r.chunk_id: r for r in (vec_rows + kw_rows)}
    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]

    out: list[Hit] = []
    for cid, score in ordered:
        if cid not in by_id:
            continue
        r = by_id[cid]
        out.append(
            Hit(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_title=r.doc_title,
                ord=r.ord,
                text=r.text,
                score=float(score),
                meta=dict(r.meta or {}),
            )
        )
    return out
