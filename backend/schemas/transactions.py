from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CreateTransactionRequest(BaseModel):
    type: str = Field(min_length=1, max_length=32)
    account_id: int | None = None
    asset_id: int | None = None
    amount: Decimal = Field(gt=0)
    quantity: Decimal | None = None
    price: Decimal | None = None
    fee: Decimal = Field(default=Decimal("0"))
    category: str | None = Field(default=None, max_length=64)
    note: str | None = None
    occurred_at: datetime


class CreateTransferRequest(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: Decimal = Field(gt=0)
    note: str | None = None
    occurred_at: datetime
