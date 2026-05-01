"""Per-model cost rates + per-call cost on token_usage.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-30
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model",
        sa.Column(
            "cost_per_1m_input_usd",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "model",
        sa.Column(
            "cost_per_1m_output_usd",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "token_usage",
        sa.Column(
            "cost_usd",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("token_usage", "cost_usd")
    op.drop_column("model", "cost_per_1m_output_usd")
    op.drop_column("model", "cost_per_1m_input_usd")
