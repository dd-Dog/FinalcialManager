from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.core.cn_banks import CHINESE_BANK_CATALOG
from backend.core.formatting import dec2
from backend.db.session import get_db
from backend.models.entities import Account, User
from backend.schemas.accounts import CreateAccountRequest
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
