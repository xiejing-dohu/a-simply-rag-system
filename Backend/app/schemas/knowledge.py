"""知识库 API 数据契约模块

包含创建知识库相关的 Pydantic Schema。
"""

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    """创建知识库请求 Schema"""

    name: str = Field(min_length=1, max_length=100, description="知识库名称")
    description: str | None = Field(default="", description="知识库描述")
    vector_dimension: int = Field(default=1024, ge=64, le=4096, description="向量维度大小")
