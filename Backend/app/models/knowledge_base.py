"""知识库模型模块

定义知识库主表（knowledge_bases），记录知识库元数据与对应的 Milvus Collection 信息。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.mysql import Base


class KnowledgeBase(Base):
    """知识库数据表映射类"""

    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    collection_name: Mapped[str] = mapped_column(
        String(191), unique=True, nullable=False, index=True
    )  # Milvus 中对应的 Collection 名称
    embedding_model: Mapped[str] = mapped_column(String(191), nullable=False)  # Embedding 模型标识
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)     # 向量维度
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)    # 知识库内文档数
    chunk_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # 知识库内向量总切片数
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )  # 状态: active / deleting
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 知识库版本代际号
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 软删除时间
    created_by: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
