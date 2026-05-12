from datetime import datetime
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
    opened_at: datetime | None = Field(
        default=None,
        description="买入日期：客户端为该日历日 0 点（本机时区）的 ISO8601；省略则用当前 UTC 日历日 0 点。",
    )


class PositionUpdateRequest(BaseModel):
    """修改已有持仓：资金账户、数量、成本单价、累计已实现盈亏（须已存在持仓行）。"""

    account_id: int = Field(ge=1)
    quantity: Decimal = Field(gt=0)
    avg_cost: Decimal = Field(gt=0)
    realized_pnl: Decimal = Field(default=Decimal("0"))
    opened_at: datetime | None = Field(
        default=None,
        description="买入日期（日历日 0 点，ISO8601）；省略则保持数据库原值。",
    )
