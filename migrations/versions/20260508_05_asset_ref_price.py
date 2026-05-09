"""assets: 定时同步的参考市价字段

Revision ID: 20260508_05
Revises: 20260507_04
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260508_05"
down_revision = "20260507_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("ref_last_price", sa.Numeric(18, 6), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column(
            "ref_price_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("assets", "ref_price_updated_at")
    op.drop_column("assets", "ref_last_price")
