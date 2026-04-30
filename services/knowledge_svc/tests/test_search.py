"""Hybrid search end-to-end on the SQLite python path."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agenticos_shared.models import Chunk, Document
from knowledge_svc.search import _cosine, _rrf, hybrid_search


def test_cosine_basics() -> None:
    assert _cosine([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert _cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert _cosine([], []) == 0.0


def test_rrf_combines_rankings() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    fused = _rrf([[a, b, c], [b, a, c]])
    assert fused[a] > fused[c]
    assert fused[b] > fused[c]


def test_hybrid_search_keyword_only(db, workspace) -> None:
    doc = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        title="Doc",
        status="ready",
        size_bytes=0,
        chunk_count=2,
        meta={},
    )
    db.add(doc)
    db.commit()

    db.add_all(
        [
            Chunk(
                id=uuid4(),
                document_id=doc.id,
                workspace_id=workspace.id,
                ord=0,
                text="The quick brown fox jumps over the lazy dog.",
                token_count=10,
                embedding=None,
                meta={},
            ),
            Chunk(
                id=uuid4(),
                document_id=doc.id,
                workspace_id=workspace.id,
                ord=1,
                text="Generic database paragraph that is unrelated.",
                token_count=10,
                embedding=None,
                meta={},
            ),
        ]
    )
    db.commit()

    hits = hybrid_search(
        db,
        workspace_id=workspace.id,
        query="quick fox",
        query_embedding=None,
        top_k=5,
    )
    assert len(hits) >= 1
    assert "fox" in hits[0].text


def test_hybrid_search_with_embeddings(db, workspace) -> None:
    doc = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        title="VecDoc",
        status="ready",
        size_bytes=0,
        chunk_count=2,
        meta={},
    )
    db.add(doc)
    db.commit()

    # Two chunks, one whose embedding aligns with the query embedding.
    aligned = [1.0, 0.0, 0.0]
    misaligned = [0.0, 1.0, 0.0]

    c1 = Chunk(
        id=uuid4(),
        document_id=doc.id,
        workspace_id=workspace.id,
        ord=0,
        text="aligned chunk text",
        token_count=3,
        embedding=aligned,
        meta={},
    )
    c2 = Chunk(
        id=uuid4(),
        document_id=doc.id,
        workspace_id=workspace.id,
        ord=1,
        text="orthogonal chunk text",
        token_count=3,
        embedding=misaligned,
        meta={},
    )
    db.add_all([c1, c2])
    db.commit()

    hits = hybrid_search(
        db,
        workspace_id=workspace.id,
        query="something completely unrelated",
        query_embedding=aligned,
        top_k=5,
    )
    # Aligned chunk should be the top hit.
    assert hits[0].chunk_id == c1.id
