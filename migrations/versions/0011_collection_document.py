"""collection_document many-to-many join (PLAN §3).

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-30
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collection_document",
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_collection_document_doc",
        "collection_document",
        ["document_id"],
    )
    # Backfill: every document with a primary collection_id gets a row.
    op.execute(
        sa.text(
            "INSERT INTO collection_document (collection_id, document_id, created_at) "
            "SELECT collection_id, id, COALESCE(updated_at, now()) "
            "FROM document WHERE collection_id IS NOT NULL "
            "ON CONFLICT DO NOTHING"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_collection_document_doc", table_name="collection_document")
    op.drop_table("collection_document")
