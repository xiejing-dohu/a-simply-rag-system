"""对话与流式聊天 API 数据契约模块

包含新建对话会话、修改对话模型与 RAG 设置、发送聊天消息相关的 Pydantic Schema。
"""

from typing import Literal

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    """创建对话会话请求 Schema"""

    title: str = "新对话"
    model_name: str | None = None
    knowledge_base_id: int | None = None
    rag_enabled: bool = False
    retrieval_mode: Literal["semantic", "dense", "hybrid"] = "semantic"
    max_retrieval_tokens: int = Field(default=2048, ge=128, le=16000, description="最大检索 Token 数量")


class ModelUpdate(BaseModel):
    """修改对话关联模型请求 Schema"""

    model_name: str


class ChatRequest(BaseModel):
    """发送聊天消息请求 Schema"""

    content: str = Field(min_length=1, description="提问消息文本")
    rag_enabled: bool = False
    knowledge_base_id: int | None = None
    retrieval_mode: Literal["semantic", "dense", "hybrid"] = "semantic"
    max_retrieval_tokens: int = Field(default=2048, ge=128, le=16000)


class RagSettingsUpdate(BaseModel):
    """更新对话 RAG 配置请求 Schema"""

    rag_enabled: bool
    knowledge_base_id: int | None = None
    retrieval_mode: Literal["semantic", "dense", "hybrid"] = "semantic"
    max_retrieval_tokens: int = Field(default=2048, ge=128, le=16000)
