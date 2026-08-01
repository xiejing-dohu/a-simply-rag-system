"""用户认证、账号注册、密码防爆破与 Token 额度管理路由模块

包含账号登录/刷新/登出、用户注册、用户信息获取及管理员维护与 Token 重置等接口。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import admin_user, current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    normalize_username,
    token_fingerprint,
    verify_password,
    verify_token,
)
from app.db.redis import redis_client
from app.schemas.auth import (
    RefreshTokenRequest,
    RegisterRequest,
    TokenUsageReset,
    UserResponse,
    UserUpdate,
)
from app.state_repository import (
    create_user,
    get_user,
    get_user_by_username,
    list_users,
    reset_user_usage,
    serialize_user,
    update_user_fields,
)

router = APIRouter(prefix="/auth", tags=["认证与用户"])


@router.post("/token")
async def login(username: Annotated[str, Form()], password: Annotated[str, Form()]):
    """用户登录接口：包含 5 分钟内连续 3 次密码错误锁定机制"""
    normalized_username = normalize_username(username)
    failure_key = f"auth:failures:{normalized_username}"
    lock_key = f"auth:lock:{normalized_username}"
    try:
        retry_after = await redis_client.ttl(lock_key)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="登录安全服务暂不可用") from exc
    if retry_after > 0:
        raise HTTPException(
            status_code=429,
            detail="密码错误次数过多，请 5 分钟后再试",
            headers={"Retry-After": str(retry_after)},
        )

    user = await get_user_by_username(normalized_username)
    if not user or not verify_password(password, user.hashed_password):
        try:
            failures = await redis_client.incr(failure_key)
            if failures == 1:
                await redis_client.expire(failure_key, 300)
            if failures >= 3:
                pipeline = redis_client.pipeline(transaction=True)
                pipeline.set(lock_key, "1", ex=300)
                pipeline.delete(failure_key)
                await pipeline.execute()
                raise HTTPException(
                    status_code=429,
                    detail="密码错误次数过多，请 5 分钟后再试",
                    headers={"Retry-After": "300"},
                )
        except RedisError as exc:
            raise HTTPException(status_code=503, detail="登录安全服务暂不可用") from exc
        raise HTTPException(status_code=401, detail="密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已停用")

    access_token = create_access_token(user.id, user.username)
    refresh_token, refresh_id = create_refresh_token(user.id, user.username)
    try:
        pipeline = redis_client.pipeline(transaction=True)
        pipeline.delete(failure_key, lock_key)
        pipeline.set(
            f"auth:refresh:{refresh_id}",
            token_fingerprint(refresh_token),
            ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        )
        await pipeline.execute()
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="登录安全服务暂不可用") from exc
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": serialize_user(user),
    }


@router.post("/refresh")
async def refresh_access_token(data: RefreshTokenRequest):
    """通过 Refresh Token 换取新的 Access Token"""
    try:
        payload = verify_token(data.refresh_token, "refresh")
        refresh_id = str(payload["jti"])
        user_id = int(payload["sub"])
        expected = await redis_client.get(f"auth:refresh:{refresh_id}")
    except (ValueError, TypeError, RedisError) as exc:
        raise HTTPException(status_code=401, detail="Refresh Token 无效或已过期") from exc
    if not expected or expected != token_fingerprint(data.refresh_token):
        raise HTTPException(status_code=401, detail="Refresh Token 无效或已过期")
    user = await get_user(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="账户不存在或已停用")
    return {
        "access_token": create_access_token(user.id, user.username),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/logout")
async def logout(data: RefreshTokenRequest):
    """用户登出：注销指定的 Refresh Token"""
    try:
        payload = verify_token(data.refresh_token, "refresh")
        await redis_client.delete(f"auth:refresh:{payload['jti']}")
    except (ValueError, RedisError):
        pass
    return {"status": "success"}


@router.post("/register", response_model=UserResponse)
async def register(data: RegisterRequest):
    """用户公开注册接口"""
    normalized_username = normalize_username(data.username)
    if len(normalized_username) < 2:
        raise HTTPException(status_code=422, detail="用户名至少需要 2 个有效字符")
    try:
        user = await create_user(
            username=normalized_username,
            email=data.email.strip().lower(),
            hashed_password=hash_password(data.password),
        )
    except IntegrityError as exc:
        message = str(exc.orig).lower()
        detail = "邮箱已存在" if "email" in message else "用户名已存在"
        raise HTTPException(status_code=409, detail=detail) from exc
    return serialize_user(user)


@router.get("/me", response_model=UserResponse)
async def get_me(user=Depends(current_user)):
    """获取当前已登录用户的个人信息及 Token 额度使用进度"""
    return serialize_user(user)


@router.get("/users", response_model=list[UserResponse])
async def get_users(_: Annotated[object, Depends(admin_user)]):
    """管理员接口：获取系统全部用户列表"""
    return [serialize_user(user) for user in await list_users()]


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, data: UserUpdate, operator=Depends(admin_user)):
    """管理员接口：更新指定用户的角色、状态或设置 Token 额度上限"""
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    changed_fields = data.model_fields_set
    if "role" in changed_fields and data.role is None:
        raise HTTPException(status_code=422, detail="用户身份不能为 null")
    if "is_active" in changed_fields and data.is_active is None:
        raise HTTPException(status_code=422, detail="账户状态不能为 null")
    if user.is_root_admin and not operator.is_root_admin and changed_fields:
        raise HTTPException(status_code=403, detail="系统管理员账户不可修改")
    if "role" in changed_fields:
        if not operator.is_root_admin:
            raise HTTPException(status_code=403, detail="只有系统管理员可以修改用户身份")
        if user.is_root_admin and data.role != "admin":
            raise HTTPException(status_code=403, detail="系统管理员身份不可更改")
    if user.is_root_admin and "is_active" in changed_fields and data.is_active is not True:
        raise HTTPException(status_code=403, detail="系统管理员账户不可停用")

    updated = await update_user_fields(
        user_id, {key: getattr(data, key) for key in changed_fields}
    )
    return serialize_user(updated)


@router.post("/users/{user_id}/token-usage/reset", response_model=UserResponse)
async def reset_user_token_usage(
    user_id: int,
    data: TokenUsageReset,
    _: Annotated[object, Depends(admin_user)],
):
    """管理员接口：手动清空重置指定用户的 5 小时或周 Token 占用量"""
    user = await reset_user_usage(user_id, data.scope)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return serialize_user(user)
