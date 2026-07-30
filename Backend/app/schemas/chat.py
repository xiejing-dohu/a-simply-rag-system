from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ConversationCreate(BaseModel):
    title: str = "新对话"
    model_name: str = "gpt-3.5-turbo"
    knowledge_base_id: Optional[int] = None

class ConversationResponse(BaseModel):
    id: int
    title: str
    model_name: str
    knowledge_base_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True

class ChatRequest(BaseModel):
    content: str

class ModelUpdateRequest(BaseModel):
    model_name: str
