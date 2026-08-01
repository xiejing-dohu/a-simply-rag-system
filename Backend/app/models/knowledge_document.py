"""知识库文档模型模块

定义已入库文档表（knowledge_documents），记录文档统计信息及对应的矢量索引元数据。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.mysql import Base


class KnowledgeDocument(Base):
    """知识库已导入文档数据表映射类"""

    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ingestion_id: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True, index=True
    )  # 幂等写入 Task UUID 映射
    name: Mapped[str] = mapped_column(String(1024), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 来源类型 (如 file / url)
    chunk_tokens: Mapped[int] = mapped_column(Integer, nullable=False)     # 切片 Token 限制
    overlap_tokens: Mapped[int] = mapped_column(Integer, nullable=False)   # 重叠 Token 限制
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)      # 生成切片数量
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)   # 该文档总 Token 数
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False) # 向量维度
    embedding_model: Mapped[str] = mapped_column(String(191), nullable=False) # Embedding 模型
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
