"""Async ingestion of an uploaded document.

The api-gateway uploads the raw bytes to MinIO under
``s3://{bucket}/uploads/{document_id}`` and enqueues this job. We:

1. Look the document up by id (it should already exist in
   ``status="pending"``).
2. Pull the bytes back from MinIO.
3. Hand the bytes to ``knowledge_svc.ingestion.ingest_document`` —
   which handles the parse → chunk → embed → persist transitions and
   marks the doc ``ready`` (or ``failed``).

If MinIO is unreachable we mark the document ``failed`` with a clear
reason; the api-gateway returns the failure on the next status poll.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agenticos_shared.db import get_sessionmaker
from agenticos_shared.logging import get_logger
from agenticos_shared.models import Document
from knowledge_svc.embedder import Embedder
from knowledge_svc.ingestion import ingest_document as _ingest_document

from ..settings import get_settings

log = get_logger(__name__)


async def _fetch_blob(*, bucket: str, key: str, settings) -> bytes:
    """Pull bytes from MinIO using boto3 if available, else httpx."""

    try:
        import boto3  # type: ignore[import-untyped]

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        obj = client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as exc:
        log.warning("ingest_blob_boto3_unavailable", error=str(exc), bucket=bucket, key=key)
        raise


async def ingest_document(
    ctx: dict[str, Any],
    document_id: str,
    *,
    s3_key: str,
    embed_alias: str | None = None,
) -> dict[str, Any]:
    """arq job: pull bytes from S3 + run the synchronous ingestion path."""

    settings = get_settings()
    sm = get_sessionmaker()
    doc_uuid = UUID(document_id)

    with sm() as db:
        doc = db.get(Document, doc_uuid)
        if doc is None:
            return {"ok": False, "reason": "document not found"}

        try:
            blob = await _fetch_blob(bucket=settings.s3_bucket, key=s3_key, settings=settings)
        except Exception as exc:
            doc.status = "failed"
            doc.error = f"s3 fetch: {exc!s}"[:1024]
            db.commit()
            return {"ok": False, "reason": doc.error}

        embedder = Embedder(
            gateway_url=settings.llm_gateway_url,
            model_alias=embed_alias or settings.default_embed_model_alias,
        )
        try:
            n = await _ingest_document(
                db,
                document_id=doc_uuid,
                blob=blob,
                embedder=embedder,
                chunk_size_tokens=400,
                chunk_overlap_tokens=60,
                max_chunks=5_000,
            )
        except Exception as exc:
            # marked doc failed; return the cause for the audit trail.
            return {"ok": False, "reason": str(exc)[:1024]}

        return {"ok": True, "chunks": n}
