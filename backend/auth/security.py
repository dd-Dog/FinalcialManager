from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from backend.core.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """标准 bcrypt 串（$2b$...），与此前 passlib 写入库的格式一致，可继续校验旧密码。"""
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("密码长度不能超过 72 字节（UTF-8 编码后）。")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        raw = plain_password.encode("utf-8")
        if len(raw) > 72:
            return False
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, username: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.jwt_expire_seconds)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("invalid token") from exc
