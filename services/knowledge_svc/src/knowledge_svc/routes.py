"""knowledge-svc HTTP API.

Internal service — accepts ``X-Workspace-Id`` header (or workspace_id
in the JSON payload) and trusts it. The api-gateway is the public face
that enforces RBAC + audit.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID, uuid4

from agenticos_shared.db import get_sessionmaker
from agenticos_shared.errors import ConflictError, NotFoundError, ValidationError
from agenticos_shared.models import Collection, Document
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .embedder import Embedder
from .ingestion import ingest_document, make_document_row
from .schemas import (
    CollectionCreate,
    CollectionOut,
    DocumentIngestRequest,
    DocumentOut,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from .search import hybrid_search
from .settings import Settings, get_settings

router = APIRouter(tags=["knowledge"])


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


def _doc_out(d: Document) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        workspace_id=d.workspace_id,
        collection_id=d.collection_id,
        title=d.title,
        mime=d.mime,
        sha256=d.sha256,
        size_bytes=d.size_bytes,
        status=d.status,
        error=d.error,
        chunk_count=d.chunk_count,
        meta=dict(d.meta or {}),
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


def _coll_out(c: Collection) -> CollectionOut:
    return CollectionOut(
        id=c.id,
        workspace_id=c.workspace_id,
        name=c.name,
        slug=c.slug,
        description=c.description,
        created_at=c.created_at,
    )


def _embedder(settings: Settings, alias: str | None) -> Embedder:
    return Embedder(
        gateway_url=settings.llm_gateway_url,
        model_alias=alias or settings.default_embed_model_alias,
        token=settings.llm_gateway_internal_token,
    )


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
@router.post(
    "/workspaces/{workspace_id}/collections",
    response_model=CollectionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_collection(
    workspace_id: UUID,
    body: CollectionCreate,
    db: Annotated[Session, Depends(get_db)],
) -> CollectionOut:
    c = Collection(
        id=uuid4(),
        workspace_id=workspace_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
    )
    db.add(c)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"collection slug '{body.slug}' already exists") from exc
    return _coll_out(c)


@router.get("/workspaces/{workspace_id}/collections", response_model=list[CollectionOut])
def list_collections(
    workspace_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> list[CollectionOut]:
    rows = (
        db.execute(
            select(Collection)
            .where(Collection.workspace_id == workspace_id)
            .order_by(Collection.name)
        )
        .scalars()
        .all()
    )
    return [_coll_out(c) for c in rows]


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@router.get("/workspaces/{workspace_id}/documents", response_model=list[DocumentOut])
def list_documents(
    workspace_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    collection_id: UUID | None = None,
) -> list[DocumentOut]:
    q = select(Document).where(Document.workspace_id == workspace_id)
    if collection_id is not None:
        q = q.where(Document.collection_id == collection_id)
    q = q.order_by(Document.created_at.desc())
    return [_doc_out(d) for d in db.execute(q).scalars().all()]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> DocumentOut:
    d = db.get(Document, document_id)
    if d is None:
        raise NotFoundError("document not found")
    return _doc_out(d)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    d = db.get(Document, document_id)
    if d is None:
        raise NotFoundError("document not found")
    db.delete(d)


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    workspace_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
    collection_id: UUID | None = Form(default=None),
    title: str | None = Form(default=None),
    embed_alias: str | None = Form(default=None),
) -> DocumentOut:
    blob = await file.read()
    if not blob:
        raise ValidationError("empty upload")

    doc = make_document_row(
        workspace_id=workspace_id,
        collection_id=collection_id,
        title=title or file.filename or "untitled",
        mime=file.content_type,
        blob=blob,
    )
    db.add(doc)
    db.commit()

    embedder = _embedder(settings, embed_alias)
    await ingest_document(
        db,
        document_id=doc.id,
        blob=blob,
        embedder=embedder,
        chunk_size_tokens=settings.chunk_size_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        max_chunks=settings.max_chunks_per_doc,
    )
    db.refresh(doc)
    return _doc_out(doc)


@router.post(
    "/workspaces/{workspace_id}/documents/text",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_text(
    workspace_id: UUID,
    body: DocumentIngestRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentOut:
    """JSON-friendly text ingestion (no multipart)."""

    if body.workspace_id != workspace_id:
        raise ValidationError("workspace_id mismatch")
    blob = body.text.encode("utf-8")
    doc = make_document_row(
        workspace_id=workspace_id,
        collection_id=body.collection_id,
        title=body.title,
        mime=body.mime or "text/plain",
        blob=blob,
    )
    db.add(doc)
    db.commit()

    embedder = _embedder(settings, body.embed_alias)
    await ingest_document(
        db,
        document_id=doc.id,
        blob=blob,
        embedder=embedder,
        chunk_size_tokens=settings.chunk_size_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        max_chunks=settings.max_chunks_per_doc,
    )
    db.refresh(doc)
    return _doc_out(doc)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    embedder = _embedder(settings, body.embed_alias)
    try:
        emb_batch = await embedder.embed_batch([body.query])
        query_vec = emb_batch[0] if emb_batch else None
    except Exception:
        # Degrade gracefully to keyword-only.
        query_vec = None

    hits = hybrid_search(
        db,
        workspace_id=body.workspace_id,
        query=body.query,
        query_embedding=query_vec,
        collection_id=body.collection_id,
        top_k=body.top_k,
    )
    return SearchResponse(
        query=body.query,
        hits=[
            SearchHit(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                document_title=h.document_title,
                ord=h.ord,
                text=h.text,
                score=h.score,
                meta=h.meta,
            )
            for h in hits
        ],
    )
