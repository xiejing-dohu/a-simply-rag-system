"""安全鉴权模块

提供密码哈希算法（PBKDF2 SHA256）、用户名规范化处理、
JWT Access Token 与 Refresh Token 的生成、校验及指纹提取功能。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# 密码加密上下文（使用 pbkdf2_sha256 算法）
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# JWT 令牌类型定义：访问令牌 (access) 或刷新令牌 (refresh)
TokenType = Literal["access", "refresh"]


def normalize_username(username: str) -> str:
    """规范化用户名

    去除首尾空格并转换为小写，保证 MySQL 查询与 Redis 锁标识的一致性。

    Args:
        username (str): 原始输入的用户名

    Returns:
        str: 规范化后的用户名
    """
    return username.strip().lower()


def hash_password(password: str) -> str:
    """对明文密码进行哈希加密

    Args:
        password (str): 明文密码

    Returns:
        str: 哈希密文
    """
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希密文是否匹配

    Args:
        plain (str): 待比对的明文密码
        hashed (str): 已存储的哈希密文

    Returns:
        bool: 匹配返回 True，否则返回 False
    """
    return pwd_context.verify(plain, hashed)


def create_token(
    *,
    user_id: int,
    username: str,
    token_type: TokenType,
    expires_delta: timedelta,
) -> tuple[str, str]:
    """底层生成 JWT 令牌的通用函数

    Args:
        user_id (int): 用户 ID
        username (str): 用户名
        token_type (TokenType): 令牌类型 ("access" 或 "refresh")
        expires_delta (timedelta): 有效时长

    Returns:
        tuple[str, str]: 包含 (生成的 JWT 字符串, 随机生成的唯一令牌 ID jti)
    """
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
    """生成短期访问令牌 Access Token

    Args:
        user_id (int): 用户 ID
        username (str): 用户名

    Returns:
        str: JWT Access Token 字符串
    """
    token, _ = create_token(
        user_id=user_id,
        username=username,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return token


def create_refresh_token(user_id: int, username: str) -> tuple[str, str]:
    """生成长期刷新令牌 Refresh Token

    Args:
        user_id (int): 用户 ID
        username (str): 用户名

    Returns:
        tuple[str, str]: (JWT Refresh Token 字符串, 令牌唯一标识 jti)
    """
    return create_token(
        user_id=user_id,
        username=username,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def verify_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """解析并校验 JWT 令牌有效性及类型

    Args:
        token (str): 传入的 JWT 字符串
        expected_type (TokenType): 期望的令牌类型 ("access" 或 "refresh")

    Raises:
        ValueError: Token 无效、已过期或令牌类型不匹配

    Returns:
        dict[str, Any]: 解密后的 Payload 字典
    """
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
    """计算令牌 SHA256 哈希指纹

    用于令牌撤销列表或 Redis 验证。

    Args:
        token (str): 令牌字符串

    Returns:
        str: 十六进制摘要指纹
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
