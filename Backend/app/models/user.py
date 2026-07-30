from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.mysql import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(
        String(191), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="employee")
    is_root_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    five_hour_token_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    weekly_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    five_hour_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    weekly_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    input_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    output_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    total_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
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
