"""positions: opened_at (买入日期锚点)

Revision ID: 20260512_06
Revises: 20260508_05
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260512_06"
down_revision = "20260508_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("positions")}
    if "opened_at" in cols:
        return
    op.add_column(
        "positions",
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("positions")}
    if "opened_at" not in cols:
        return
    op.drop_column("positions", "opened_at")
