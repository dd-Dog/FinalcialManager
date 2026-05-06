from decimal import Decimal

from pydantic import BaseModel, Field


class CreateAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    account_type: str = Field(min_length=1, max_length=32)
    currency: str = Field(default="CNY", min_length=1, max_length=8)
    initial_balance: Decimal = Field(default=Decimal("0"))
    owner_name: str | None = Field(default=None, max_length=64)
    bank_code: str | None = Field(default=None, max_length=32)
