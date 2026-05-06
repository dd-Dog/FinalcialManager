from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.db.session import get_db
from backend.models.entities import Asset, User
from backend.schemas.assets import CreateAssetRequest
from backend.schemas.common import APIResponse

router = APIRouter()


@router.get("", response_model=APIResponse)
def list_assets(
    asset_type: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    query = select(Asset).where(Asset.user_id == current_user.id).order_by(Asset.id.desc())
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if symbol:
        query = query.where(Asset.symbol == symbol)

    assets = db.scalars(query).all()
    items = [
        {
            "id": asset.id,
            "asset_type": asset.asset_type,
            "symbol": asset.symbol,
            "name": asset.name,
            "market": asset.market,
        }
        for asset in assets
    ]
    return APIResponse(data={"items": items})


@router.post("", response_model=APIResponse)
def create_asset(
    payload: CreateAssetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    asset = Asset(
        user_id=current_user.id,
        asset_type=payload.asset_type.lower(),
        symbol=payload.symbol.upper(),
        name=payload.name,
        market=payload.market,
    )
    db.add(asset)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Asset already exists") from exc
    db.refresh(asset)
    return APIResponse(
        data={
            "id": asset.id,
            "asset_type": asset.asset_type,
            "symbol": asset.symbol,
            "name": asset.name,
            "market": asset.market,
        }
    )
