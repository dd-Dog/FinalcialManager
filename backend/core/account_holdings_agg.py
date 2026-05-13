"""按资金账户汇总证券持仓市值（参考价盯市，无参考价时退回成本口径）。"""

from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.models.entities import Asset, Position


def account_holdings_market_value_map(db: Session, user_id: int) -> dict[int, Decimal]:
    """每个 ``account_id`` 上持仓的市值合计：``sum(数量 × (参考市价若存在否则成本单价))``。

    与持仓列表「浮动盈亏」所用参考价一致；无参考价时用账面成本，避免该行被完全忽略。
    """
    line = Position.quantity * case(
        (Asset.ref_last_price.isnot(None), Asset.ref_last_price),
        else_=Position.avg_cost,
    )
    stmt = (
        select(Position.account_id, func.coalesce(func.sum(line), 0))
        .join(Asset, Position.asset_id == Asset.id)
        .where(
            Position.user_id == user_id,
            Position.account_id.isnot(None),
            Asset.user_id == user_id,
        )
        .group_by(Position.account_id)
    )
    out: dict[int, Decimal] = {}
    for aid, raw in db.execute(stmt).all():
        if aid is None:
            continue
        out[int(aid)] = Decimal(str(raw or 0))
    return out
