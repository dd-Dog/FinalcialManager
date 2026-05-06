"""transactions: per-sell realized_pnl snapshot

Revision ID: 20260506_03
Revises: 20260502_02
Create Date: 2026-05-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260506_03"
down_revision = "20260502_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("realized_pnl", sa.Numeric(18, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "realized_pnl")
