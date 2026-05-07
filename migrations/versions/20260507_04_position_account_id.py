"""positions: optional custody account (资金账户)

Revision ID: 20260507_04
Revises: 20260506_03
Create Date: 2026-05-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260507_04"
down_revision = "20260506_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column("account_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_positions_account_id",
        "positions",
        "accounts",
        ["account_id"],
        ["id"],
    )
    op.create_index("idx_positions_account_id", "positions", ["account_id"])


def downgrade() -> None:
    op.drop_index("idx_positions_account_id", table_name="positions")
    op.drop_constraint("fk_positions_account_id", "positions", type_="foreignkey")
    op.drop_column("positions", "account_id")
