from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MYSQL_HOST: str
    MYSQL_PORT: int
    MYSQL_USER: str
    MYSQL_PASSWORD: str
    MYSQL_DATABASE: str
    
    MILVUS_HOST: str
    MILVUS_PORT: int
    
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    
    OPENAI_API_KEY: str
    OPENAI_API_BASE: str
    DEFAULT_MODEL: str
    
    EMBEDDING_MODEL: str
    
    class Config:
        env_file = ".env"

settings = Settings()
