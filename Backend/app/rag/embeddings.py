from langchain_openai import OpenAIEmbeddings
from app.core.config import settings

def get_embedding_model():
    """获取 OpenAI Embedding 模型"""
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_API_BASE
    )
