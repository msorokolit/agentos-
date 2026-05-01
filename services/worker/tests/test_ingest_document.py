"""Worker ingest_document job: pulls bytes from S3, runs full ingestion."""

from __future__ import annotations

from uuid import uuid4

import pytest
import respx
from agenticos_shared import db as shared_db
from agenticos_shared.models import Base, Document, Tenant, Workspace
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _bind(db_engine, monkeypatch):
    sm = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(shared_db, "_engine", db_engine, raising=False)
    monkeypatch.setattr(shared_db, "_SessionLocal", sm, raising=False)


@pytest.mark.asyncio
async def test_ingest_document_happy_path(db_engine, monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    from worker import settings as st

    st.get_settings.cache_clear()

    sm = sessionmaker(bind=db_engine, future=True)
    with sm() as db:
        t = Tenant(id=uuid4(), slug="acme", name="Acme")
        db.add(t)
        db.flush()
        w = Workspace(id=uuid4(), tenant_id=t.id, slug="default", name="Default")
        db.add(w)
        db.flush()
        d = Document(
            id=uuid4(),
            workspace_id=w.id,
            title="x.txt",
            mime="text/plain",
            sha256="x",
            size_bytes=11,
            status="pending",
            chunk_count=0,
            meta={},
        )
        db.add(d)
        db.commit()
        doc_id = d.id

    # Replace the S3 fetcher with one that returns canned bytes.
    from worker.jobs import ingest_document as job_mod

    async def fake_fetch(*, bucket, key, settings):
        return b"hello there from worker"

    monkeypatch.setattr(job_mod, "_fetch_blob", fake_fetch)

    with respx.mock() as router:
        router.post("http://llm-gateway:8081/v1/embeddings").respond(
            200,
            json={
                "object": "list",
                "model": "embed-default",
                "data": [{"object": "embedding", "embedding": [1.0, 0.0], "index": 0}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
            },
        )
        out = await job_mod.ingest_document({}, str(doc_id), s3_key=f"uploads/{doc_id}")
    assert out["ok"] is True
    assert out["chunks"] >= 1

    with sm() as db:
        d = db.get(Document, doc_id)
        assert d.status == "ready"
        assert d.chunk_count >= 1


@pytest.mark.asyncio
async def test_ingest_document_marks_failed_when_s3_dies(db_engine, monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    from worker import settings as st

    st.get_settings.cache_clear()

    sm = sessionmaker(bind=db_engine, future=True)
    with sm() as db:
        t = Tenant(id=uuid4(), slug="acme", name="Acme")
        db.add(t)
        db.flush()
        w = Workspace(id=uuid4(), tenant_id=t.id, slug="default", name="Default")
        db.add(w)
        db.flush()
        d = Document(
            id=uuid4(),
            workspace_id=w.id,
            title="x.txt",
            mime="text/plain",
            sha256="x",
            size_bytes=1,
            status="pending",
            chunk_count=0,
            meta={},
        )
        db.add(d)
        db.commit()
        doc_id = d.id

    from worker.jobs import ingest_document as job_mod

    async def boom(*, bucket, key, settings):
        raise RuntimeError("s3 unreachable")

    monkeypatch.setattr(job_mod, "_fetch_blob", boom)

    out = await job_mod.ingest_document({}, str(doc_id), s3_key="x")
    assert out["ok"] is False
    assert "s3 unreachable" in out["reason"]

    with sm() as db:
        d = db.get(Document, doc_id)
        assert d.status == "failed"
        assert d.error and "s3 unreachable" in d.error
