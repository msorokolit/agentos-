"""Add model + token_usage tables (Phase 2).

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-30
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("alias", sa.String(length=128), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=32),  # native_enum=False uses VARCHAR + check constraint
            nullable=False,
        ),
        sa.Column("endpoint", sa.String(length=512), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="chat"),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("default_params", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("alias", name="uq_model_alias"),
        sa.CheckConstraint(
            "provider IN ('ollama','vllm','openai_compat')",
            name="ck_model_provider",
        ),
        sa.CheckConstraint(
            "kind IN ('chat','embedding')",
            name="ck_model_kind",
        ),
    )
    op.create_index("ix_model_alias", "model", ["alias"])

    op.create_table(
        "token_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_alias", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_token_usage_created_at", "token_usage", ["created_at"])
    op.create_index(
        "ix_token_usage_workspace_created", "token_usage", ["workspace_id", "created_at"]
    )
    op.create_index("ix_token_usage_alias_created", "token_usage", ["model_alias", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_token_usage_alias_created", table_name="token_usage")
    op.drop_index("ix_token_usage_workspace_created", table_name="token_usage")
    op.drop_index("ix_token_usage_created_at", table_name="token_usage")
    op.drop_table("token_usage")
    op.drop_index("ix_model_alias", table_name="model")
    op.drop_table("model")
