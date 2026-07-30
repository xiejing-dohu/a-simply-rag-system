from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(
    *,
    user_id: int,
    username: str,
    token_type: TokenType,
    expires_delta: timedelta,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    token_id = secrets.token_urlsafe(24)
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": token_type,
        "jti": token_id,
        "iat": now,
        "exp": now + expires_delta,
    }
    return (
        jwt.encode(
            payload,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        ),
        token_id,
    )


def create_access_token(user_id: int, username: str) -> str:
    token, _ = create_token(
        user_id=user_id,
        username=username,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return token


def create_refresh_token(user_id: int, username: str) -> tuple[str, str]:
    return create_token(
        user_id=user_id,
        username=username,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def verify_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise ValueError("Token 无效或已过期") from exc
    if payload.get("type") != expected_type or not payload.get("sub"):
        raise ValueError("Token 类型无效")
    return payload


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
