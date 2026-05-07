from decimal import Decimal

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.core.cn_banks import CHINESE_BANK_CATALOG
from backend.core.formatting import dec2
from backend.db.session import get_db
from backend.models.entities import Account, Transaction, TransferRecord, User
from backend.schemas.accounts import CreateAccountRequest, UpdateAccountRequest
from backend.schemas.common import APIResponse

router = APIRouter()


@router.get("/bank-catalog", response_model=APIResponse)
def chinese_bank_catalog(_user: User = Depends(get_current_user)) -> APIResponse:
    return APIResponse(data={"items": CHINESE_BANK_CATALOG})


@router.get("", response_model=APIResponse)
def list_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    accounts = db.scalars(select(Account).where(Account.user_id == current_user.id).order_by(Account.id.desc())).all()
    items = [
        {
            "id": account.id,
            "name": account.name,
            "account_type": account.account_type,
            "owner_name": account.owner_name,
            "bank_code": account.bank_code,
            "currency": account.currency,
            "balance": dec2(account.balance),
            "is_active": account.is_active,
        }
        for account in accounts
    ]
    return APIResponse(data={"items": items})


@router.post("", response_model=APIResponse)
def create_account(
    payload: CreateAccountRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    bank_code = payload.bank_code.strip() if payload.bank_code else None
    if bank_code and payload.account_type != "bank":
        bank_code = None
    if payload.account_type == "bank" and bank_code:
        valid_codes = {b["code"] for b in CHINESE_BANK_CATALOG}
        if bank_code not in valid_codes:
            bank_code = None

    owner = payload.owner_name.strip() if payload.owner_name else None

    account = Account(
        user_id=current_user.id,
        name=payload.name.strip(),
        account_type=payload.account_type,
        owner_name=owner,
        bank_code=bank_code,
        currency=payload.currency.upper(),
        balance=Decimal(payload.initial_balance),
        is_active=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return APIResponse(
        data={
            "id": account.id,
            "name": account.name,
            "account_type": account.account_type,
            "owner_name": account.owner_name,
            "bank_code": account.bank_code,
            "currency": account.currency,
            "balance": dec2(account.balance),
        }
    )


@router.patch("/{account_id}", response_model=APIResponse)
def update_account(
    account_id: int,
    payload: UpdateAccountRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    account = db.scalar(
        select(Account).where(Account.id == account_id, Account.user_id == current_user.id)
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "name" in data:
        nm = str(data["name"] or "").strip()
        if not nm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name cannot be empty")
        account.name = nm
    if "owner_name" in data:
        raw = data["owner_name"]
        account.owner_name = (str(raw).strip() or None) if raw is not None else None
    if "currency" in data and data["currency"] is not None:
        account.currency = str(data["currency"]).strip().upper()
    if "is_active" in data and data["is_active"] is not None:
        account.is_active = bool(data["is_active"])

    if "bank_code" in data:
        if account.account_type != "bank":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="bank_code only applies to bank accounts",
            )
        raw_bc = data["bank_code"]
        bc = (str(raw_bc).strip() or None) if raw_bc is not None else None
        if bc:
            valid_codes = {b["code"] for b in CHINESE_BANK_CATALOG}
            if bc not in valid_codes:
                bc = None
        account.bank_code = bc

    account.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(account)
    return APIResponse(
        data={
            "id": account.id,
            "name": account.name,
            "account_type": account.account_type,
            "owner_name": account.owner_name,
            "bank_code": account.bank_code,
            "currency": account.currency,
            "balance": dec2(account.balance),
            "is_active": account.is_active,
        }
    )


@router.delete("/{account_id}", response_model=APIResponse)
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    account = db.scalar(
        select(Account).where(Account.id == account_id, Account.user_id == current_user.id)
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    if Decimal(str(account.balance or 0)) != Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete account with non-zero balance",
        )

    tx_cnt = int(
        db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user_id == current_user.id, Transaction.account_id == account_id)
        )
        or 0
    )
    if tx_cnt > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete account: related transactions exist",
        )

    tr_cnt = int(
        db.scalar(
            select(func.count())
            .select_from(TransferRecord)
            .where(
                TransferRecord.user_id == current_user.id,
                or_(
                    TransferRecord.from_account_id == account_id,
                    TransferRecord.to_account_id == account_id,
                ),
            )
        )
        or 0
    )
    if tr_cnt > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete account: related transfers exist",
        )

    db.delete(account)
    db.commit()
    return APIResponse(data={"id": account_id, "deleted": True})
