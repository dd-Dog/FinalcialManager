"""init financial tables

Revision ID: 20260430_01
Revises:
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260430_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(length=64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
        sa.Column("balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("idx_accounts_user_id", "accounts", ["user_id"])
    op.create_index("idx_accounts_type", "accounts", ["account_type"])

    op.create_table(
        "assets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("market", sa.String(length=32)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("user_id", "asset_type", "symbol", name="uq_assets_user_type_symbol"),
    )
    op.create_index("idx_assets_user_id", "assets", ["user_id"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id")),
        sa.Column("asset_id", sa.BigInteger(), sa.ForeignKey("assets.id")),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6)),
        sa.Column("price", sa.Numeric(18, 6)),
        sa.Column("fee", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("category", sa.String(length=64)),
        sa.Column("note", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_transactions_amount_non_negative"),
    )
    op.create_index("idx_transactions_user_time", "transactions", ["user_id", "occurred_at"])
    op.create_index("idx_transactions_type", "transactions", ["type"])
    op.create_index("idx_transactions_account", "transactions", ["account_id"])
    op.create_index("idx_transactions_asset", "transactions", ["asset_id"])

    op.create_table(
        "transfer_records",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("transaction_id", sa.BigInteger(), sa.ForeignKey("transactions.id"), nullable=False, unique=True),
        sa.Column("from_account_id", sa.BigInteger(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("to_account_id", sa.BigInteger(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_transfer_amount_positive"),
        sa.CheckConstraint("from_account_id <> to_account_id", name="ck_transfer_diff_accounts"),
    )
    op.create_index("idx_transfer_user_id", "transfer_records", ["user_id"])

    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("avg_cost", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("user_id", "asset_id", name="uq_positions_user_asset"),
    )
    op.create_index("idx_positions_user_id", "positions", ["user_id"])

    op.create_table(
        "income_expense_tags",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tag_key", sa.String(length=64), nullable=False),
        sa.Column("tag_name", sa.String(length=128), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("user_id", "tag_key", name="uq_tags_user_key"),
    )


def downgrade() -> None:
    op.drop_table("income_expense_tags")
    op.drop_index("idx_positions_user_id", table_name="positions")
    op.drop_table("positions")
    op.drop_index("idx_transfer_user_id", table_name="transfer_records")
    op.drop_table("transfer_records")
    op.drop_index("idx_transactions_asset", table_name="transactions")
    op.drop_index("idx_transactions_account", table_name="transactions")
    op.drop_index("idx_transactions_type", table_name="transactions")
    op.drop_index("idx_transactions_user_time", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("idx_assets_user_id", table_name="assets")
    op.drop_table("assets")
    op.drop_index("idx_accounts_type", table_name="accounts")
    op.drop_index("idx_accounts_user_id", table_name="accounts")
    op.drop_table("accounts")
    op.drop_table("users")
