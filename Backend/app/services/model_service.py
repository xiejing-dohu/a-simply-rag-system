from app.schemas.model import ModelInfo
from langchain_openai import ChatOpenAI
from app.core.config import settings

def get_available_models() -> list[ModelInfo]:
    """返回预定义的模型列表"""
    return [
        ModelInfo(id="gpt-3.5-turbo", name="GPT-3.5 Turbo", description="速度快，性价比高", provider="OpenAI"),
        ModelInfo(id="gpt-4", name="GPT-4", description="能力强，适用于复杂任务", provider="OpenAI"),
        ModelInfo(id="gpt-4o", name="GPT-4o", description="最新多模态旗舰模型", provider="OpenAI")
    ]

def get_llm_instance(model_name: str):
    """LLM 工厂"""
    return ChatOpenAI(
        model_name=model_name,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_API_BASE,
        streaming=True
    )
