"""用户模型模块

定义系统用户表（users）及 Token 额度、使用量统计等关联字段。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.mysql import Base


class User(Base):
    """用户数据表映射类"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(
        String(191), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="employee")  # 角色：admin / employee 等
    is_root_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )  # 是否为根超级管理员
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 额度限制（Token 数）
    five_hour_token_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )  # 5小时内 Token 额度上限
    weekly_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 周 Token 额度上限

    # 消耗 Token 统计
    five_hour_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )  # 5小时窗口内已使用 Token 数
    weekly_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )  # 周窗口内已使用 Token 数
    input_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )  # 累计输入 Token 数
    output_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )  # 累计输出 Token 数
    total_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )  # 累计总 Token 数

    # 统计时间窗口起点
    five_hour_window_started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    weekly_window_started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
