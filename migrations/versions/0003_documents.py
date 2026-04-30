"""Add collection, document, chunk tables; create pgvector extension and
upgrade chunk.embedding to vector(EMBED_DIM) on PostgreSQL.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-30
"""

from __future__ import annotations

import os
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # pgvector extension (best-effort).
    if is_pg:
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.create_table(
        "collection",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_collection_ws_slug"),
    )
    op.create_index("ix_collection_slug", "collection", ["slug"])

    op.create_table(
        "document",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("source_uri", sa.String(length=1024), nullable=True),
        sa.Column("mime", sa.String(length=128), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','parsing','embedding','ready','failed')",
            name="ck_document_status",
        ),
    )
    op.create_index("ix_document_sha256", "document", ["sha256"])
    op.create_index(
        "ix_document_workspace_created", "document", ["workspace_id", "created_at"]
    )

    op.create_table(
        "chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_chunk_document_ord", "chunk", ["document_id", "ord"])
    op.create_index(
        "ix_chunk_workspace_created", "chunk", ["workspace_id", "created_at"]
    )

    # On PostgreSQL with pgvector available, swap embedding to vector(N)
    # and add a tsvector column for hybrid search.
    if is_pg:
        op.execute(
            sa.text(
                f"ALTER TABLE chunk ALTER COLUMN embedding TYPE vector({EMBED_DIM}) "
                "USING NULL::vector"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE chunk ADD COLUMN tsv tsvector "
                "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED"
            )
        )
        op.execute(sa.text("CREATE INDEX ix_chunk_tsv ON chunk USING GIN (tsv)"))
        op.execute(
            sa.text(
                "CREATE INDEX ix_chunk_embedding ON chunk USING ivfflat "
                "(embedding vector_cosine_ops) WITH (lists = 100)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if is_pg:
        op.execute(sa.text("DROP INDEX IF EXISTS ix_chunk_embedding"))
        op.execute(sa.text("DROP INDEX IF EXISTS ix_chunk_tsv"))
        op.execute(sa.text("ALTER TABLE chunk DROP COLUMN IF EXISTS tsv"))

    op.drop_index("ix_chunk_workspace_created", table_name="chunk")
    op.drop_index("ix_chunk_document_ord", table_name="chunk")
    op.drop_table("chunk")
    op.drop_index("ix_document_workspace_created", table_name="document")
    op.drop_index("ix_document_sha256", table_name="document")
    op.drop_table("document")
    op.drop_index("ix_collection_slug", table_name="collection")
    op.drop_table("collection")
