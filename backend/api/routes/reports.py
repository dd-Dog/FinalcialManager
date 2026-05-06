from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, extract, func, select
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.core.formatting import dec2, dec2_opt
from backend.db.session import get_db
from backend.models.entities import Account, Asset, Position, Transaction, User
from backend.schemas.common import APIResponse

router = APIRouter()


@router.get("/wealth-overview", response_model=APIResponse)
def wealth_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """现金各账户余额 + 持仓按成本估值（未接行情，非盯市总市值）。"""
    cash_total = db.scalar(
        select(func.coalesce(func.sum(Account.balance), 0)).where(
            Account.user_id == current_user.id,
            Account.is_active.is_(True),
        )
    )
    cash_total = Decimal(cash_total or 0)

    rows = db.execute(
        select(Position, Asset)
        .join(Asset, Position.asset_id == Asset.id)
        .where(Position.user_id == current_user.id, Asset.user_id == current_user.id)
        .order_by(Asset.asset_type, Asset.symbol)
    ).all()

    pos_items: list[dict] = []
    book = Decimal(0)
    for position, asset in rows:
        qty = Decimal(position.quantity)
        ac = Decimal(position.avg_cost)
        bv = qty * ac
        book += bv
        pos_items.append(
            {
                "asset_id": asset.id,
                "asset_type": asset.asset_type,
                "symbol": asset.symbol,
                "name": asset.name,
                "quantity": dec2(qty),
                "avg_cost": dec2(ac),
                "book_value": dec2(bv),
                "realized_pnl": dec2(position.realized_pnl),
            }
        )

    accounts_out = [
        {
            "id": a.id,
            "name": a.name,
            "account_type": a.account_type,
            "balance": dec2(a.balance),
            "currency": a.currency,
        }
        for a in db.scalars(
            select(Account)
            .where(Account.user_id == current_user.id, Account.is_active.is_(True))
            .order_by(Account.id.desc())
        ).all()
    ]

    grand = cash_total + book

    return APIResponse(
        data={
            "cash_total": dec2(cash_total),
            "position_book_value_total": dec2(book),
            "grand_book_total": dec2(grand),
            "accounts": accounts_out,
            "positions": pos_items,
            "note": "合计为各账户余额 + 持仓数量×成本；未含证券盯市涨跌。",
        }
    )


@router.get("/monthly-income", response_model=APIResponse)
def monthly_income(
    year: int | None = Query(default=None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """按自然月汇总「收入」类流水（type=income）。"""
    y = year if year is not None else datetime.now().year
    month_bucket = func.date_trunc("month", Transaction.occurred_at)
    stmt = (
        select(month_bucket.label("period"), func.coalesce(func.sum(Transaction.amount - Transaction.fee), 0).label("total"))
        .where(
            Transaction.user_id == current_user.id,
            Transaction.type == "income",
            extract("year", Transaction.occurred_at) == y,
        )
        .group_by(month_bucket)
        .order_by(month_bucket)
    )
    rows = db.execute(stmt).all()
    items = []
    for r in rows:
        p = r.period
        month_key = p.strftime("%Y-%m") if hasattr(p, "strftime") else str(p)[:7]
        items.append({"month": month_key, "total": dec2(r.total)})
    return APIResponse(data={"year": y, "items": items})


@router.get("/pnl-overview", response_model=APIResponse)
def pnl_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """持仓累计已实现盈亏 + 卖出流水（含单笔 realized_pnl）。"""
    pos_total = db.scalar(
        select(func.coalesce(func.sum(Position.realized_pnl), 0)).where(Position.user_id == current_user.id)
    )
    pos_total = Decimal(pos_total or 0)

    pos_rows = db.execute(
        select(Position, Asset)
        .join(Asset, Position.asset_id == Asset.id)
        .where(Position.user_id == current_user.id, Asset.user_id == current_user.id)
        .order_by(Asset.symbol)
    ).all()
    positions = [
        {
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "quantity": dec2(position.quantity),
            "avg_cost": dec2(position.avg_cost),
            "realized_pnl": dec2(position.realized_pnl),
        }
        for position, asset in pos_rows
    ]

    sell_rows = db.execute(
        select(Transaction, Asset)
        .join(Asset, Transaction.asset_id == Asset.id)
        .where(Transaction.user_id == current_user.id, Transaction.type == "sell")
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        .limit(200)
    ).all()
    sells = [
        {
            "id": tx.id,
            "occurred_at": tx.occurred_at.isoformat(),
            "symbol": asset.symbol,
            "name": asset.name,
            "quantity": dec2_opt(tx.quantity),
            "amount": dec2(tx.amount),
            "fee": dec2(tx.fee),
            "realized_pnl": dec2_opt(tx.realized_pnl),
        }
        for tx, asset in sell_rows
    ]

    return APIResponse(
        data={
            "position_realized_pnl_total": dec2(pos_total),
            "positions": positions,
            "sell_ledger": sells,
        }
    )


@router.get("/pnl", response_model=APIResponse)
def pnl_report(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    conditions = [Transaction.user_id == current_user.id]
    if start_date is not None:
        conditions.append(Transaction.occurred_at >= start_date)
    if end_date is not None:
        conditions.append(Transaction.occurred_at <= end_date)

    income_expr = case(
        (
            Transaction.type.in_(["income", "dividend", "sell", "transfer_in"]),
            Transaction.amount - Transaction.fee,
        ),
        else_=0,
    )
    expense_expr = case(
        (
            Transaction.type.in_(["expense", "buy", "transfer_out"]),
            Transaction.amount + Transaction.fee,
        ),
        else_=0,
    )

    income_total, expense_total = db.execute(
        select(
            func.coalesce(func.sum(income_expr), 0),
            func.coalesce(func.sum(expense_expr), 0),
        ).where(*conditions)
    ).one()

    income_total = Decimal(income_total)
    expense_total = Decimal(expense_total)
    net_total = income_total - expense_total

    return APIResponse(
        data={
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "income_total": dec2(income_total),
            "expense_total": dec2(expense_total),
            "net_total": dec2(net_total),
        }
    )


@router.get("/cashflow-summary", response_model=APIResponse)
def cashflow_summary(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """收支报表：现金类收入、实际支出；股票/基金为期内卖出已实现盈亏汇总（不含买卖本金）。"""
    conditions = [Transaction.user_id == current_user.id]
    if start_date is not None:
        conditions.append(Transaction.occurred_at >= start_date)
    if end_date is not None:
        conditions.append(Transaction.occurred_at <= end_date)

    income_expr = case(
        (
            Transaction.type.in_(["income", "dividend", "transfer_in"]),
            Transaction.amount - Transaction.fee,
        ),
        else_=0,
    )
    expense_expr = case(
        (
            Transaction.type.in_(["expense", "transfer_out"]),
            Transaction.amount + Transaction.fee,
        ),
        else_=0,
    )

    income_total, expense_total = db.execute(
        select(
            func.coalesce(func.sum(income_expr), 0),
            func.coalesce(func.sum(expense_expr), 0),
        ).where(*conditions)
    ).one()

    income_total = Decimal(income_total)
    expense_total = Decimal(expense_total)

    sell_base = [
        Transaction.user_id == current_user.id,
        Transaction.type == "sell",
    ]
    if start_date is not None:
        sell_base.append(Transaction.occurred_at >= start_date)
    if end_date is not None:
        sell_base.append(Transaction.occurred_at <= end_date)

    stock_gain = db.scalar(
        select(func.coalesce(func.sum(func.coalesce(Transaction.realized_pnl, 0)), 0))
        .select_from(Transaction)
        .join(Asset, Transaction.asset_id == Asset.id)
        .where(*sell_base, Asset.user_id == current_user.id, Asset.asset_type == "stock")
    )
    fund_gain = db.scalar(
        select(func.coalesce(func.sum(func.coalesce(Transaction.realized_pnl, 0)), 0))
        .select_from(Transaction)
        .join(Asset, Transaction.asset_id == Asset.id)
        .where(*sell_base, Asset.user_id == current_user.id, Asset.asset_type == "fund")
    )
    stock_gain_total = Decimal(stock_gain or 0)
    fund_gain_total = Decimal(fund_gain or 0)
    gross_income_total = income_total + stock_gain_total + fund_gain_total
    net_total = gross_income_total - expense_total

    return APIResponse(
        data={
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "gross_income_total": dec2(gross_income_total),
            "income_total": dec2(income_total),
            "stock_gain_total": dec2(stock_gain_total),
            "fund_gain_total": dec2(fund_gain_total),
            "expense_total": dec2(expense_total),
            "net_total": dec2(net_total),
        }
    )
