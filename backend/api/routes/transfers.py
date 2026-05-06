from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.db.session import get_db
from backend.models.entities import Account, Transaction, TransferRecord, User
from backend.schemas.common import APIResponse
from backend.schemas.transactions import CreateTransferRequest

router = APIRouter()


@router.post("", response_model=APIResponse)
def create_transfer(
    payload: CreateTransferRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    if payload.from_account_id == payload.to_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="from_account_id cannot equal to_account_id")

    from_account = db.scalar(
        select(Account)
        .where(
            Account.id == payload.from_account_id,
            Account.user_id == current_user.id,
            Account.is_active.is_(True),
        )
        .with_for_update()
    )
    to_account = db.scalar(
        select(Account)
        .where(
            Account.id == payload.to_account_id,
            Account.user_id == current_user.id,
            Account.is_active.is_(True),
        )
        .with_for_update()
    )
    if from_account is None or to_account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer account not found")

    amount = Decimal(payload.amount)
    if Decimal(from_account.balance) < amount:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient balance")

    transfer_tx = Transaction(
        user_id=current_user.id,
        type="transfer",
        account_id=payload.from_account_id,
        amount=amount,
        fee=Decimal("0"),
        category="transfer",
        note=payload.note,
        occurred_at=payload.occurred_at,
    )

    try:
        from_account.balance = Decimal(from_account.balance) - amount
        to_account.balance = Decimal(to_account.balance) + amount
        db.add(transfer_tx)
        db.flush()

        transfer_record = TransferRecord(
            user_id=current_user.id,
            transaction_id=transfer_tx.id,
            from_account_id=payload.from_account_id,
            to_account_id=payload.to_account_id,
            amount=amount,
        )
        db.add(transfer_record)
        db.commit()
        db.refresh(transfer_tx)
        db.refresh(transfer_record)
    except Exception:
        db.rollback()
        raise

    return APIResponse(
        data={
            "transaction_id": transfer_tx.id,
            "transfer_record_id": transfer_record.id,
        }
    )
