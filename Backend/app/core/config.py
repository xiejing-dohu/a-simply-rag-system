"""应用全局配置模块

使用 pydantic-settings 从环境变量或 `.env` 文件读取系统配置项，
包含数据库、Milvus 向量库、JWT 鉴权、Redis 及 LLM/Embedding/Rerank 配置。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置类

    自动加载本地 `.env` 配置文件中的配置项，未列出的环境变量将被忽略。
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MySQL 数据库连接配置
    MYSQL_HOST: str
    MYSQL_PORT: int
    MYSQL_USER: str
    MYSQL_PASSWORD: str
    MYSQL_DATABASE: str

    # Milvus 向量数据库连接配置
    MILVUS_HOST: str
    MILVUS_PORT: int

    # JWT 身份验证配置
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # Access Token 有效期（分钟）
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7       # Refresh Token 有效期（天）

    # Redis 服务连接 URL
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # 文档并发处理 Worker 数量
    DOCUMENT_WORKER_CONCURRENCY: int = 2

    # OpenAI / LLM 服务 API 配置
    OPENAI_API_KEY: str
    OPENAI_API_BASE: str
    DEFAULT_MODEL: str  # 默认使用的大语言模型名称

    # Embedding 嵌入模型配置
    EMBEDDING_MODEL: str

    # Rerank 重排序模型配置
    RERANK_PROVIDER: str = "none"        # 重排序提供商（如 none, bge, custom 等）
    RERANK_MODEL: str = "qwen3-rerank"   # 重排序模型名称
    RERANK_API_URL: str = ""             # 重排序服务 API 接口地址
    RERANK_API_KEY: str = ""             # 重排序服务 API 密钥


# 全局单例配置对象
settings = Settings()
