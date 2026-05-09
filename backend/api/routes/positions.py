from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.core.formatting import dec2, dec2_opt
from backend.db.session import get_db
from backend.models.entities import Account, Asset, Position, Transaction, User
from backend.schemas.common import APIResponse
from backend.schemas.positions import PositionUpdateRequest, UpsertOpeningPositionRequest

router = APIRouter()

_QTY_EPS = Decimal("1e-9")


def _trade_tx_count(db: Session, user_id: int, asset_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.asset_id == asset_id,
                Transaction.type.in_(("buy", "sell")),
            )
        )
        or 0
    )


def _position_qty(position: Position | None) -> Decimal:
    if position is None:
        return Decimal("0")
    return Decimal(str(position.quantity or 0))


def _dec_close(a: object, b: object) -> bool:
    return abs(Decimal(str(a)) - Decimal(str(b))) < Decimal("1e-8")


@router.get("", response_model=APIResponse)
def list_positions(
    asset_type: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    query = (
        select(Position, Asset, Account)
        .join(Asset, Position.asset_id == Asset.id)
        .outerjoin(Account, Position.account_id == Account.id)
        .where(Position.user_id == current_user.id, Asset.user_id == current_user.id)
        .order_by(Position.id.desc())
    )
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if symbol:
        query = query.where(Asset.symbol == symbol)

    rows = db.execute(query).all()

    def _cash_account_label(acc: Account | None) -> str | None:
        if acc is None:
            return None
        return f"{acc.name} ({acc.account_type})"

    holdings: list[dict] = []
    items: list[dict] = []
    hold_fund_book = Decimal(0)
    hold_stock_book = Decimal(0)
    hold_other_book = Decimal(0)

    for position, asset, account in rows:
        qty_d = Decimal(str(position.quantity or 0))
        ac_d = Decimal(str(position.avg_cost or 0))
        lp_dec: Decimal | None = None
        fp_dec: Decimal | None = None
        if abs(qty_d) > _QTY_EPS and asset.ref_last_price is not None:
            lp_dec = Decimal(str(asset.ref_last_price))
            fp_dec = qty_d * (lp_dec - ac_d)

        ca_lbl = _cash_account_label(account)
        item_row = {
            "cash_account": ca_lbl,
            "asset_id": asset.id,
            "asset_type": asset.asset_type,
            "symbol": asset.symbol,
            "name": asset.name,
            "account_id": position.account_id,
            "quantity": dec2(position.quantity),
            "avg_cost": dec2(position.avg_cost),
            "cost_amount": dec2(qty_d * ac_d),
            "realized_pnl": dec2(position.realized_pnl),
            "last_price": dec2_opt(lp_dec) if lp_dec is not None else None,
            "floating_pnl": dec2_opt(fp_dec) if fp_dec is not None else None,
        }
        items.append(item_row)

        if abs(qty_d) > _QTY_EPS:
            bv_h = qty_d * ac_d
            at_l = (asset.asset_type or "").strip().lower()
            if at_l == "fund":
                hold_fund_book += bv_h
            elif at_l == "stock":
                hold_stock_book += bv_h
            else:
                hold_other_book += bv_h
            h = {k: v for k, v in item_row.items() if k != "realized_pnl"}
            holdings.append(h)

    sell_rows = db.execute(
        select(Transaction, Asset)
        .join(Asset, Transaction.asset_id == Asset.id)
        .where(Transaction.user_id == current_user.id, Transaction.type == "sell")
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        .limit(10)
    ).all()
    recent_sells = [
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
            "items": items,
            "holdings": holdings,
            "recent_sells": recent_sells,
            "holdings_book_by_type": {
                "fund": dec2(hold_fund_book),
                "stock": dec2(hold_stock_book),
                "other": dec2(hold_other_book),
            },
        }
    )


@router.post("/opening", response_model=APIResponse)
def upsert_opening_position(
    payload: UpsertOpeningPositionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """补录/修正持仓数量与成本单价（可选累计已实现盈亏）；默认不允许覆盖已有持仓或存在证券流水时误写。"""
    asset = db.scalar(select(Asset).where(Asset.id == payload.asset_id, Asset.user_id == current_user.id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    cust = db.scalar(
        select(Account).where(
            Account.id == payload.account_id,
            Account.user_id == current_user.id,
            Account.is_active.is_(True),
        )
    )
    if cust is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    trade_cnt = _trade_tx_count(db, current_user.id, asset.id)
    position = db.scalar(select(Position).where(Position.user_id == current_user.id, Position.asset_id == asset.id))
    qty_existing = _position_qty(position)
    blocked = (abs(qty_existing) > _QTY_EPS) or trade_cnt > 0
    if blocked and not payload.replace_existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Existing position or buy/sell transactions; set replace_existing to true to overwrite",
        )

    q = Decimal(payload.quantity)
    c = Decimal(payload.avg_cost)
    rp = Decimal(payload.realized_pnl)

    if position is None:
        position = Position(
            user_id=current_user.id,
            asset_id=asset.id,
            account_id=cust.id,
            quantity=q,
            avg_cost=c,
            realized_pnl=rp,
        )
        db.add(position)
    else:
        position.quantity = q
        position.avg_cost = c
        position.realized_pnl = rp
        position.account_id = cust.id
        position.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(position)
    return APIResponse(
        data={
            "asset_id": asset.id,
            "account_id": position.account_id,
            "quantity": dec2(position.quantity),
            "avg_cost": dec2(position.avg_cost),
            "realized_pnl": dec2(position.realized_pnl),
        }
    )


@router.patch("/by-asset/{asset_id}", response_model=APIResponse)
def update_position_by_asset(
    asset_id: int,
    payload: PositionUpdateRequest,
    replace_existing: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """修改已有持仓（含补录资金账户）；若存在证券买卖流水且改动数量/成本/已实现盈亏，须 ``replace_existing=true``。"""
    asset = db.scalar(select(Asset).where(Asset.id == asset_id, Asset.user_id == current_user.id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    position = db.scalar(select(Position).where(Position.user_id == current_user.id, Position.asset_id == asset.id))
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found for this asset")

    cust = db.scalar(
        select(Account).where(
            Account.id == payload.account_id,
            Account.user_id == current_user.id,
            Account.is_active.is_(True),
        )
    )
    if cust is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    trade_cnt = _trade_tx_count(db, current_user.id, asset.id)
    qty_ch = not _dec_close(position.quantity, payload.quantity)
    cost_ch = not _dec_close(position.avg_cost, payload.avg_cost)
    rp_ch = not _dec_close(position.realized_pnl, payload.realized_pnl)
    if trade_cnt > 0 and (qty_ch or cost_ch or rp_ch) and not replace_existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Buy/sell history exists; set replace_existing=true to change quantity, cost, or realized P&L",
        )

    position.quantity = Decimal(payload.quantity)
    position.avg_cost = Decimal(payload.avg_cost)
    position.realized_pnl = Decimal(payload.realized_pnl)
    position.account_id = cust.id
    position.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(position)
    return APIResponse(
        data={
            "asset_id": asset.id,
            "account_id": position.account_id,
            "quantity": dec2(position.quantity),
            "avg_cost": dec2(position.avg_cost),
            "realized_pnl": dec2(position.realized_pnl),
        }
    )
