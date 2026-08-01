"""向量库异步操作事务收件箱 (Outbox) 模型模块

定义向量数据库同步队列表（vector_operations），用于保证分布式场景下 Milvus 操作的事务可靠性与最终一致性。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.mysql import Base


class VectorOperation(Base):
    """Milvus 幂等操作异步 Outbox 数据表映射类"""

    __tablename__ = "vector_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # 节点 UUID
    idempotency_key: Mapped[str] = mapped_column(
        String(191), unique=True, nullable=False, index=True
    )  # 幂等键
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 操作类型 (如 create_collection, drop_collection, insert, delete)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)   # 资源类型 (如 knowledge_base, knowledge_document)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True) # 资源 ID
    collection_name: Mapped[str] = mapped_column(String(191), nullable=False)     # 目标 Milvus 集合
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)     # 补充载荷数据
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # 状态: pending, completed, failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)        # 当前重试次数
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=10)     # 最大重试次数
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )  # 下一次重试触发时间
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 上次执行错误日志
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
