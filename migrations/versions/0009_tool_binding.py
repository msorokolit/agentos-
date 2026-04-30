"""tool_binding join table.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-30
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_binding",
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tool.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_tool_binding_tool", "tool_binding", ["tool_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_binding_tool", table_name="tool_binding")
    op.drop_table("tool_binding")
