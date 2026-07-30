from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    MYSQL_HOST: str
    MYSQL_PORT: int
    MYSQL_USER: str
    MYSQL_PASSWORD: str
    MYSQL_DATABASE: str
    
    MILVUS_HOST: str
    MILVUS_PORT: int
    
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    
    OPENAI_API_KEY: str
    OPENAI_API_BASE: str
    DEFAULT_MODEL: str
    
    EMBEDDING_MODEL: str

    RERANK_PROVIDER: str = "none"
    RERANK_MODEL: str = "qwen3-rerank"
    RERANK_API_URL: str = ""
    RERANK_API_KEY: str = ""

settings = Settings()
