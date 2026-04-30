"""Memory items.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-30
"""

from __future__ import annotations

import os
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    op.create_table(
        "memory_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "scope IN ('user','agent','session','workspace')",
            name="ck_memory_scope",
        ),
    )
    op.create_index("ix_memory_workspace_scope", "memory_item", ["workspace_id", "scope"])
    op.create_index("ix_memory_owner", "memory_item", ["scope", "owner_id"])

    if is_pg:
        op.execute(
            sa.text(
                f"ALTER TABLE memory_item ALTER COLUMN embedding TYPE vector({EMBED_DIM}) "
                "USING NULL::vector"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX ix_memory_embedding ON memory_item USING ivfflat "
                "(embedding vector_cosine_ops) WITH (lists = 50)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if is_pg:
        op.execute(sa.text("DROP INDEX IF EXISTS ix_memory_embedding"))
    op.drop_index("ix_memory_owner", table_name="memory_item")
    op.drop_index("ix_memory_workspace_scope", table_name="memory_item")
    op.drop_table("memory_item")
