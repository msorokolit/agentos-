"""Policy bundles: uploaded Rego with versioning + active flag.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-30
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_bundle",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("package", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rego", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "package IN ('tool_access','data_access','model_access')",
            name="ck_policy_package",
        ),
    )
    op.create_index(
        "ix_policy_active", "policy_bundle", ["tenant_id", "package", "active"]
    )
    op.create_index(
        "ix_policy_name_version",
        "policy_bundle",
        ["tenant_id", "package", "name", "version"],
    )


def downgrade() -> None:
    op.drop_index("ix_policy_name_version", table_name="policy_bundle")
    op.drop_index("ix_policy_active", table_name="policy_bundle")
    op.drop_table("policy_bundle")
