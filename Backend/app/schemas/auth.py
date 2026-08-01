"""用户认证与权限额度 API 数据契约模块

包含用户注册、信息响应、密码修改、额度限制及令牌刷新相关的 Pydantic Schema。
"""

from typing import Literal

from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    """用户信息及 Token 额度使用响应 Schema"""

    id: int
    username: str
    email: str
    role: Literal["admin", "employee"] = "employee"
    is_root_admin: bool = False
    is_active: bool = True
    created_at: str
    five_hour_token_limit: int | None = None
    weekly_token_limit: int | None = None
    five_hour_tokens_used: int = 0
    weekly_tokens_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    total_tokens_used: int = 0
    five_hour_window_started_at: str
    weekly_window_started_at: str
    five_hour_resets_at: str
    weekly_resets_at: str


class RegisterRequest(BaseModel):
    """用户注册请求 Schema"""

    model_config = {"extra": "forbid"}

    username: str = Field(min_length=2, max_length=50, description="用户名（2-50字符）")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="电子邮箱格式")
    password: str = Field(min_length=6, description="密码（最少6位）")


class UserUpdate(BaseModel):
    """管理员更新用户信息请求 Schema"""

    role: Literal["admin", "employee"] | None = None
    is_active: bool | None = None
    five_hour_token_limit: int | None = Field(default=None, ge=1, description="5小时 Token 额度上限")
    weekly_token_limit: int | None = Field(default=None, ge=1, description="周 Token 额度上限")


class TokenUsageReset(BaseModel):
    """Token 使用量重置请求 Schema"""

    scope: Literal["five_hour", "weekly", "all"]  # 重置范围：5小时、每周或全部


class RefreshTokenRequest(BaseModel):
    """刷新 Token 请求 Schema"""

    refresh_token: str = Field(min_length=20, description="刷新令牌")
