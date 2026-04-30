"""Ingestion orchestrator: parse → chunk → embed → store.

Used both inline (small text uploads) and as a worker job.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agenticos_shared.errors import NotFoundError
from agenticos_shared.logging import get_logger
from agenticos_shared.models import Chunk as ChunkRow
from agenticos_shared.models import Document
from sqlalchemy.orm import Session

from .chunker import chunk_text, count_tokens
from .embedder import Embedder
from .ingest import extract_text

log = get_logger(__name__)


async def ingest_document(
    db: Session,
    *,
    document_id: UUID,
    blob: bytes,
    embedder: Embedder,
    chunk_size_tokens: int,
    chunk_overlap_tokens: int,
    max_chunks: int,
) -> int:
    """End-to-end ingestion for an existing ``document`` row.

    Returns the number of chunks produced.
    """

    doc = db.get(Document, document_id)
    if doc is None:
        raise NotFoundError("document not found")

    doc.status = "parsing"
    doc.updated_at = datetime.now(tz=UTC)
    db.commit()

    try:
        extracted = extract_text(blob=blob, mime=doc.mime, filename=doc.title)
        # Pre-existing meta is preserved.
        doc.meta = {**(doc.meta or {}), **extracted.meta}

        chunks = chunk_text(
            extracted.text,
            chunk_size=chunk_size_tokens,
            overlap=chunk_overlap_tokens,
        )
        if len(chunks) > max_chunks:
            chunks = chunks[:max_chunks]

        if not chunks:
            doc.status = "ready"
            doc.chunk_count = 0
            doc.updated_at = datetime.now(tz=UTC)
            db.commit()
            return 0

        # Embed in batches.
        doc.status = "embedding"
        db.commit()

        BATCH = 32
        embeddings: list[list[float]] = []
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i : i + BATCH]
            vecs = await embedder.embed_batch([c.text for c in batch])
            embeddings.extend(vecs)

        # Persist chunks.
        for c, vec in zip(chunks, embeddings, strict=True):
            db.add(
                ChunkRow(
                    id=uuid4(),
                    document_id=doc.id,
                    workspace_id=doc.workspace_id,
                    ord=c.ord,
                    text=c.text,
                    token_count=c.token_count,
                    embedding=vec or None,
                    meta=c.meta or {},
                )
            )
        doc.status = "ready"
        doc.chunk_count = len(chunks)
        doc.updated_at = datetime.now(tz=UTC)
        db.commit()
        return len(chunks)

    except Exception as exc:
        log.exception("ingest_failed", error=str(exc), document_id=str(document_id))
        doc.status = "failed"
        doc.error = str(exc)[:1024]
        doc.updated_at = datetime.now(tz=UTC)
        db.commit()
        raise


def make_document_row(
    *,
    workspace_id: UUID,
    collection_id: UUID | None,
    title: str,
    mime: str | None,
    blob: bytes,
) -> Document:
    return Document(
        id=uuid4(),
        workspace_id=workspace_id,
        collection_id=collection_id,
        title=title,
        mime=mime,
        sha256=hashlib.sha256(blob).hexdigest(),
        size_bytes=len(blob),
        status="pending",
        chunk_count=0,
        meta={},
    )


def estimate_tokens(text: str) -> int:
    return count_tokens(text)
