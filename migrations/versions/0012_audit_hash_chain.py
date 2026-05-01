"""audit_event hash chain (prev_hash, event_hash).

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-01
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_event",
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "audit_event",
        sa.Column("event_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_audit_event_event_hash",
        "audit_event",
        ["event_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_event_event_hash", table_name="audit_event")
    op.drop_column("audit_event", "event_hash")
    op.drop_column("audit_event", "prev_hash")
