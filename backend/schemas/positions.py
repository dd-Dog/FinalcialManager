from decimal import Decimal

from pydantic import BaseModel, Field


class UpsertOpeningPositionRequest(BaseModel):
    """补录已有持仓：写入或覆盖 ``positions`` 行（不自动生成买卖流水）。"""

    asset_id: int = Field(ge=1)
    account_id: int = Field(ge=1)
    quantity: Decimal = Field(gt=0)
    avg_cost: Decimal = Field(gt=0)
    realized_pnl: Decimal = Field(default=Decimal("0"))
    replace_existing: bool = False


class PositionUpdateRequest(BaseModel):
    """修改已有持仓：资金账户、数量、成本单价、累计已实现盈亏（须已存在持仓行）。"""

    account_id: int = Field(ge=1)
    quantity: Decimal = Field(gt=0)
    avg_cost: Decimal = Field(gt=0)
    realized_pnl: Decimal = Field(default=Decimal("0"))
