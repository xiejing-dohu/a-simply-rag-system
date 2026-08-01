"""对话会话模型模块

定义系统对话表（conversations），记录用户创建的对话会话及 RAG/模型参数设置。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.mysql import Base


class Conversation(Base):
    """对话会话数据表映射类"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新对话")
    model_name: Mapped[str] = mapped_column(String(191), nullable=False)  # 使用的大语言模型标识
    knowledge_base_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True
    )  # 关联的知识库 ID
    rag_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 是否启用 RAG 检索增强
    retrieval_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="semantic"
    )  # 检索模式 (如 semantic / hybrid 等)
    max_retrieval_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2048
    )  # 检索上下文的最大 Token 数
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
