"""对话消息模型模块

定义消息表（messages），记录对话历史中的 Role、内容及引用的 RAG 检索上下文。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.mysql import Base


class Message(Base):
    """对话消息数据表映射类"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 角色: system, user, assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)     # 消息文本内容
    rag_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # RAG 引用文档上下文 JSON 结构
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
