from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.core.formatting import dec2, dec2_opt
from backend.db.session import get_db
from backend.models.entities import Account, Asset, Position, Transaction, TransferRecord, User
from backend.schemas.common import APIResponse
from backend.schemas.transactions import CreateTransactionRequest

router = APIRouter()


@router.get("", response_model=APIResponse)
def list_transactions(
    type: str | None = Query(default=None),
    account_id: int | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    conditions = [Transaction.user_id == current_user.id]
    if type:
        conditions.append(Transaction.type == type)
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    if start_date is not None:
        conditions.append(Transaction.occurred_at >= start_date)
    if end_date is not None:
        conditions.append(Transaction.occurred_at <= end_date)

    total = db.scalar(select(func.count()).select_from(Transaction).where(*conditions)) or 0
    offset = (page - 1) * page_size
    transactions = db.scalars(
        select(Transaction)
        .where(*conditions)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    items = [
        {
            "id": tx.id,
            "type": tx.type,
            "account_id": tx.account_id,
            "asset_id": tx.asset_id,
            "amount": dec2(tx.amount),
            "quantity": dec2_opt(tx.quantity),
            "price": dec2_opt(tx.price),
            "fee": dec2(tx.fee),
            "realized_pnl": dec2_opt(tx.realized_pnl),
            "category": tx.category,
            "note": tx.note,
            "occurred_at": tx.occurred_at.isoformat(),
        }
        for tx in transactions
    ]
    return APIResponse(
        data={
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
            },
        }
    )


def _account_brief(acc: Account | None) -> dict | None:
    if acc is None:
        return None
    return {
        "id": acc.id,
        "name": acc.name,
        "account_type": acc.account_type,
        "owner_name": acc.owner_name,
        "currency": acc.currency,
    }


def _asset_brief(asset: Asset | None) -> dict | None:
    if asset is None:
        return None
    return {
        "id": asset.id,
        "symbol": asset.symbol,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "market": asset.market,
    }


@router.get("/{transaction_id}", response_model=APIResponse)
def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    tx = db.scalar(select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == current_user.id))
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    data: dict[str, object] = {
        "id": tx.id,
        "type": tx.type,
        "account_id": tx.account_id,
        "asset_id": tx.asset_id,
        "amount": dec2(tx.amount),
        "quantity": dec2_opt(tx.quantity),
        "price": dec2_opt(tx.price),
        "fee": dec2(tx.fee),
        "realized_pnl": dec2_opt(tx.realized_pnl),
        "category": tx.category,
        "note": tx.note,
        "occurred_at": tx.occurred_at.isoformat(),
    }

    if tx.account_id is not None:
        acc = db.scalar(select(Account).where(Account.id == tx.account_id, Account.user_id == current_user.id))
        data["account"] = _account_brief(acc)

    if tx.asset_id is not None:
        asset = db.scalar(select(Asset).where(Asset.id == tx.asset_id, Asset.user_id == current_user.id))
        data["asset"] = _asset_brief(asset)

    if tx.type == "transfer":
        tr = db.scalar(select(TransferRecord).where(TransferRecord.transaction_id == tx.id))
        if tr is not None:
            from_acc = db.scalar(select(Account).where(Account.id == tr.from_account_id, Account.user_id == current_user.id))
            to_acc = db.scalar(select(Account).where(Account.id == tr.to_account_id, Account.user_id == current_user.id))
            data["transfer"] = {
                "from_account_id": tr.from_account_id,
                "to_account_id": tr.to_account_id,
                "amount": dec2(tr.amount),
                "from_account": _account_brief(from_acc),
                "to_account": _account_brief(to_acc),
            }

    return APIResponse(data=data)


@router.post("", response_model=APIResponse)
def create_transaction(
    payload: CreateTransactionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    trade_types = {"buy", "sell"}
    account = None
    if payload.account_id is not None:
        account = db.scalar(
            select(Account).where(Account.id == payload.account_id, Account.user_id == current_user.id, Account.is_active.is_(True))
        )
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    asset = None
    if payload.asset_id is not None:
        asset = db.scalar(select(Asset).where(Asset.id == payload.asset_id, Asset.user_id == current_user.id))
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if payload.type in trade_types:
        if payload.asset_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="asset_id is required for buy/sell")
        if payload.quantity is None or payload.price is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quantity and price are required for buy/sell")

    tx_realized: Decimal | None = None

    # MVP balance rule: income/dividend increase balance, expense/buy decrease balance.
    if account is not None:
        decrease_types = {"expense", "buy", "transfer_out"}
        increase_types = {"income", "dividend", "sell", "transfer_in"}
        if payload.type in decrease_types:
            delta = Decimal(payload.amount) + Decimal(payload.fee)
            if Decimal(account.balance) < delta:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient balance")
            account.balance = Decimal(account.balance) - delta
        elif payload.type in increase_types:
            account.balance = Decimal(account.balance) + Decimal(payload.amount) - Decimal(payload.fee)

    if payload.type in trade_types and asset is not None:
        quantity = Decimal(payload.quantity)
        price = Decimal(payload.price)
        fee = Decimal(payload.fee)
        position = db.scalar(select(Position).where(Position.user_id == current_user.id, Position.asset_id == asset.id))
        if position is None:
            position = Position(
                user_id=current_user.id,
                asset_id=asset.id,
                quantity=Decimal("0"),
                avg_cost=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
            db.add(position)
            db.flush()

        current_qty = Decimal(position.quantity)
        current_avg_cost = Decimal(position.avg_cost)
        current_realized = Decimal(position.realized_pnl)
        if payload.type == "buy":
            new_qty = current_qty + quantity
            total_cost = current_qty * current_avg_cost + quantity * price
            position.quantity = new_qty
            position.avg_cost = (total_cost / new_qty) if new_qty > 0 else Decimal("0")
        else:
            if current_qty < quantity:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient position quantity")
            realized = (price - current_avg_cost) * quantity - fee
            new_qty = current_qty - quantity
            position.quantity = new_qty
            position.avg_cost = current_avg_cost if new_qty > 0 else Decimal("0")
            position.realized_pnl = current_realized + realized
            tx_realized = realized

    tx = Transaction(
        user_id=current_user.id,
        type=payload.type,
        account_id=payload.account_id,
        asset_id=payload.asset_id,
        amount=Decimal(payload.amount),
        quantity=payload.quantity,
        price=payload.price,
        fee=Decimal(payload.fee),
        realized_pnl=tx_realized,
        category=payload.category,
        note=payload.note,
        occurred_at=payload.occurred_at,
    )

    db.add(tx)
    db.commit()
    db.refresh(tx)
    return APIResponse(data={"id": tx.id})
