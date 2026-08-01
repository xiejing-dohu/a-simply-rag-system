"""文档处理异步任务模型模块

定义文档解析、切片及向量化异步任务数据表（document_tasks）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.mysql import Base


class DocumentTask(Base):
    """文档异步任务数据表映射类"""

    __tablename__ = "document_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # 任务 UUID
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    temp_path: Mapped[str] = mapped_column(String(2048), nullable=False)  # 临时存储路径
    chunk_tokens: Mapped[int] = mapped_column(Integer, nullable=False)     # 单块 Token 大小
    overlap_tokens: Mapped[int] = mapped_column(Integer, nullable=False)   # 切片重叠 Token 数
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", index=True
    )  # 任务状态: queued, processing, completed, failed
    stage: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")  # 阶段描述
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)        # 进度百分比 (0-100)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)        # 重试次数
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )  # Worker 心跳时间戳
    result_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True
    )  # 处理成功生成的文档 ID
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败错误信息
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
