from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.core.formatting import dec2
from backend.db.session import get_db
from backend.models.entities import Asset, Position, Transaction, User
from backend.schemas.assets import CreateAssetRequest, UpdateAssetRequest
from backend.schemas.common import APIResponse

router = APIRouter()

_QTY_EPS = Decimal("1e-9")


def _position_quantity(db: Session, user_id: int, asset_id: int) -> Decimal:
    pos = db.scalar(select(Position).where(Position.user_id == user_id, Position.asset_id == asset_id))
    if pos is None:
        return Decimal("0")
    return Decimal(str(pos.quantity or 0))


def _has_open_position(db: Session, user_id: int, asset_id: int) -> bool:
    return abs(_position_quantity(db, user_id, asset_id)) > _QTY_EPS


def _tx_count_for_asset(db: Session, user_id: int, asset_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user_id == user_id, Transaction.asset_id == asset_id)
        )
        or 0
    )


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
    qty_by_id: dict[int, Decimal] = {}
    if assets:
        asset_ids = [a.id for a in assets]
        for pos in db.scalars(
            select(Position).where(Position.user_id == current_user.id, Position.asset_id.in_(asset_ids))
        ).all():
            qty_by_id[pos.asset_id] = Decimal(str(pos.quantity or 0))

    items = []
    for asset in assets:
        pq = qty_by_id.get(asset.id, Decimal("0"))
        items.append(
            {
                "id": asset.id,
                "asset_type": asset.asset_type,
                "symbol": asset.symbol,
                "name": asset.name,
                "market": asset.market,
                "position_quantity": dec2(pq),
                "has_open_position": abs(pq) > _QTY_EPS,
            }
        )
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


@router.patch("/{asset_id}", response_model=APIResponse)
def update_asset(
    asset_id: int,
    payload: UpdateAssetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    asset = db.scalar(select(Asset).where(Asset.id == asset_id, Asset.user_id == current_user.id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if _has_open_position(db, current_user.id, asset_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update asset while holding a non-zero position",
        )

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "name" in data:
        nm = str(data["name"] or "").strip()
        if not nm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name cannot be empty")
        asset.name = nm
    if "market" in data:
        raw = data["market"]
        asset.market = (str(raw).strip() or None) if raw is not None else None
    if "asset_type" in data and data["asset_type"] is not None:
        asset.asset_type = str(data["asset_type"]).strip().lower()
    if "symbol" in data and data["symbol"] is not None:
        sym = str(data["symbol"]).strip().upper()
        if not sym:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="symbol cannot be empty")
        asset.symbol = sym

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


@router.delete("/{asset_id}", response_model=APIResponse)
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    asset = db.scalar(select(Asset).where(Asset.id == asset_id, Asset.user_id == current_user.id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if _has_open_position(db, current_user.id, asset_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete asset while holding a non-zero position",
        )

    if _tx_count_for_asset(db, current_user.id, asset_id) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete asset: related transactions exist",
        )

    pos = db.scalar(select(Position).where(Position.user_id == current_user.id, Position.asset_id == asset_id))
    if pos is not None:
        db.delete(pos)

    db.delete(asset)
    db.commit()
    return APIResponse(data={"id": asset_id, "deleted": True})
