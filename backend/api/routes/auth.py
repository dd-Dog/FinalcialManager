from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.security import create_access_token, hash_password, verify_password
from backend.core.config import settings
from backend.db.session import get_db
from backend.models.entities import User
from backend.schemas.auth import LoginRequest, RegisterRequest
from backend.schemas.common import APIResponse
from fastapi import Depends

router = APIRouter()


@router.post("/register", response_model=APIResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> APIResponse:
    existing = db.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc
    db.refresh(user)
    return APIResponse(data={"id": user.id, "username": user.username})


@router.post("/login", response_model=APIResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> APIResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(user.id, user.username)
    return APIResponse(
        data={
            "access_token": token,
            "token_type": "bearer",
            "expires_in": settings.jwt_expire_seconds,
        }
    )
