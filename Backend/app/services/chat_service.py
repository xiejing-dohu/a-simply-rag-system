from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import AsyncGenerator
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.chat import ConversationCreate
from app.rag.chains import build_rag_chain, stream_chat
from app.models.knowledge_base import KnowledgeBase

async def create_conversation(db: AsyncSession, user_id: int, data: ConversationCreate) -> Conversation:
    conv = Conversation(
        user_id=user_id,
        title=data.title,
        model_name=data.model_name,
        knowledge_base_id=data.knowledge_base_id
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv

async def get_user_conversations(db: AsyncSession, user_id: int) -> list[Conversation]:
    result = await db.execute(select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc()))
    return list(result.scalars().all())

async def delete_conversation(db: AsyncSession, conversation_id: int, user_id: int) -> bool:
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
    conv = result.scalar_one_or_none()
    if not conv:
        return False
    await db.delete(conv)
    await db.commit()
    return True

async def get_messages(db: AsyncSession, conversation_id: int) -> list[Message]:
    result = await db.execute(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc()))
    return list(result.scalars().all())

async def save_message(db: AsyncSession, conversation_id: int, role: str, content: str) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg

async def send_message_stream(db: AsyncSession, conversation_id: int, user_id: int, content: str) -> AsyncGenerator:
    # 验证会话并获取
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
    conv = result.scalar_one_or_none()
    if not conv:
        yield "Error: Conversation not found"
        return

    # 获取历史消息
    hist_messages = await get_messages(db, conversation_id)
    history = [(msg.role, msg.content) for msg in hist_messages]

    # 保存用户消息
    await save_message(db, conversation_id, "user", content)
    
    collection_name = None
    if conv.knowledge_base_id:
        kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == conv.knowledge_base_id))
        kb = kb_result.scalar_one_or_none()
        if kb:
            collection_name = kb.collection_name

    chain = build_rag_chain(conv.model_name, collection_name)
    
    full_response = ""
    async for chunk in stream_chat(chain, content, history):
        full_response += chunk
        yield chunk
        
    # 保存AI回复
    await save_message(db, conversation_id, "assistant", full_response)
