"""表格列名：随界面语言显示中文或英文（见 finance_i18n 的 col_* 键）。"""
from __future__ import annotations

from finance_i18n import t

# 与 finance_i18n 中 col_{key} 一一对应；未列出的字段名将格式化为 Title Case
_COLUMN_I18N_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "symbol",
        "account_type",
        "owner_name",
        "bank_code",
        "currency",
        "balance",
        "is_active",
        "asset_id",
        "asset_type",
        "market",
        "position_quantity",
        "has_open_position",
        "quantity",
        "avg_cost",
        "realized_pnl",
        "book_value",
        "seq",
        "type",
        "account_id",
        "account",
        "asset",
        "amount",
        "price",
        "fee",
        "category",
        "note",
        "occurred_at",
        "transaction_id",
        "transfer_record_id",
        "from_account_id",
        "to_account_id",
        "month",
        "total",
        "start_date",
        "end_date",
        "income_total",
        "expense_total",
        "net_total",
        "cash_total",
        "position_book_value_total",
        "grand_book_total",
        "position_realized_pnl_total",
        "code",
        "year",
        "pagination",
        "page",
        "page_size",
        "items",
        "created_at",
        "updated_at",
    }
)


def column_label(key: str) -> str:
    if key in _COLUMN_I18N_KEYS:
        return t(f"col_{key}")
    return key.replace("_", " ").strip().title()


def apply_table_column_labels(
    rows: list[dict],
    *,
    preserve_keys: frozenset[str] | None = None,
) -> list[dict]:
    """将字段名转为当前语言的表头；``preserve_keys`` 中的键保持原名（供 ``column_config`` 绑定）。"""
    if not rows:
        return rows
    pk = preserve_keys or frozenset()
    out: list[dict] = []
    for row in rows:
        new_row: dict[str, object] = {}
        for k, v in row.items():
            if k in pk:
                new_row[k] = v
            else:
                new_row[column_label(k)] = v
        out.append(new_row)
    return out
