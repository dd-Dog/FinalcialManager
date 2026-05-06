"""表格列名：统一为「English / 中文」，避免直接展示数据库字段名。"""
from __future__ import annotations

# 字段名 -> 表头（双语）；未列出的键将使用 _fallback_label
COLUMN_LABELS: dict[str, str] = {
    "id": "ID / 编号",
    "name": "Name / 名称",
    "symbol": "Symbol / 代码",
    "account_type": "Account type / 账户类型",
    "owner_name": "Owner / 户主",
    "bank_code": "Bank code / 银行代码",
    "currency": "Currency / 币种",
    "balance": "Balance / 余额",
    "is_active": "Active / 启用",
    "asset_id": "Asset ID / 标的ID",
    "asset_type": "Asset type / 标的类型",
    "market": "Market / 市场",
    "quantity": "Quantity / 数量",
    "avg_cost": "Avg cost / 成本价",
    "realized_pnl": "Realized P&L / 已实现盈亏",
    "book_value": "Book value / 账面价值",
    "seq": "No. / 序号",
    "type": "Type / 类型",
    "account_id": "Account ID / 账户ID",
    "account": "Account / 账户",
    "asset": "Asset / 标的",
    "amount": "Amount / 金额",
    "price": "Price / 单价",
    "fee": "Fee / 手续费",
    "category": "Category / 类别",
    "note": "Note / 备注",
    "occurred_at": "Occurred at / 发生时间",
    "transaction_id": "Transaction ID / 流水ID",
    "transfer_record_id": "Transfer ID / 转账记录ID",
    "from_account_id": "From account ID / 转出账户ID",
    "to_account_id": "To account ID / 转入账户ID",
    "month": "Month / 月份",
    "total": "Total / 合计",
    "start_date": "Start / 开始时间",
    "end_date": "End / 结束时间",
    "income_total": "Income total / 收入合计",
    "expense_total": "Expense total / 支出合计",
    "net_total": "Net total / 净额",
    "cash_total": "Cash total / 现金合计",
    "position_book_value_total": "Positions at cost / 持仓成本合计",
    "grand_book_total": "Grand total (book) / 账面总资产",
    "position_realized_pnl_total": "Realized P&L total / 已实现盈亏合计",
    "code": "Code / 代码",
    "year": "Year / 年份",
    "pagination": "Pagination / 分页",
    "page": "Page / 页码",
    "page_size": "Page size / 每页条数",
    "items": "Items / 条目",
    "created_at": "Created at / 创建时间",
    "updated_at": "Updated at / 更新时间",
}


def _fallback_label(key: str) -> str:
    h = key.replace("_", " ").strip().title()
    return f"{h} / {key}"


def apply_table_column_labels(
    rows: list[dict],
    *,
    preserve_keys: frozenset[str] | None = None,
) -> list[dict]:
    """将字段名转为双语表头；``preserve_keys`` 中的键保持原名（供 ``column_config`` 绑定）。"""
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
                label = COLUMN_LABELS.get(k) or _fallback_label(k)
                new_row[label] = v
        out.append(new_row)
    return out
