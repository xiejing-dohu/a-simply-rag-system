"""FastAPI HTTP 请求鉴权与依赖注入模块

提供提取 Bearer Token、验证当前登录用户身份及校验管理员权限的 Depends 依赖注入函数。
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.core.security import verify_token
from app.state_repository import get_user


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    """提取 Header 中的 Bearer Token 字符串"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    return authorization.removeprefix("Bearer ").strip()


async def current_user(token: Annotated[str, Depends(bearer_token)]):
    """验证 Access Token 有效性并获取当前登录的用户实体对象"""
    try:
        payload = verify_token(token, "access")
        user_id = int(payload["sub"])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="登录已失效") from exc
    user = await get_user(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="登录已失效")
    return user


def admin_user(user=Depends(current_user)):
    """校验当前用户是否具有管理员 (admin) 权限"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
