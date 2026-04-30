"""Add tool registry table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-30
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("descriptor", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("workspace_id", "name", name="uq_tool_ws_name"),
        sa.CheckConstraint(
            "kind IN ('builtin','http','openapi','mcp')",
            name="ck_tool_kind",
        ),
    )
    op.create_index("ix_tool_name", "tool", ["name"])


def downgrade() -> None:
    op.drop_index("ix_tool_name", table_name="tool")
    op.drop_table("tool")
