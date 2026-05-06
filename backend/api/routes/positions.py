from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.core.formatting import dec2
from backend.db.session import get_db
from backend.models.entities import Asset, Position, User
from backend.schemas.common import APIResponse

router = APIRouter()


@router.get("", response_model=APIResponse)
def list_positions(
    asset_type: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    query = (
        select(Position, Asset)
        .join(Asset, Position.asset_id == Asset.id)
        .where(Position.user_id == current_user.id, Asset.user_id == current_user.id)
        .order_by(Position.id.desc())
    )
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if symbol:
        query = query.where(Asset.symbol == symbol)

    rows = db.execute(query).all()
    items = [
        {
            "asset_id": asset.id,
            "asset_type": asset.asset_type,
            "symbol": asset.symbol,
            "name": asset.name,
            "quantity": dec2(position.quantity),
            "avg_cost": dec2(position.avg_cost),
            "realized_pnl": dec2(position.realized_pnl),
        }
        for position, asset in rows
    ]
    return APIResponse(data={"items": items})
