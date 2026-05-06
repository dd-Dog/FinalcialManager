"""account owner_name and bank_code

Revision ID: 20260502_02
Revises: 20260430_01
Create Date: 2026-05-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260502_02"
down_revision = "20260430_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("owner_name", sa.String(length=64), nullable=True))
    op.add_column("accounts", sa.Column("bank_code", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "bank_code")
    op.drop_column("accounts", "owner_name")
