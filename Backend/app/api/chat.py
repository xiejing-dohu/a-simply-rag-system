from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from sse_starlette.sse import EventSourceResponse
from app.core.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.chat import ConversationCreate, ConversationResponse, MessageResponse, ChatRequest, ModelUpdateRequest
from app.services import chat_service
import asyncio

router = APIRouter()

@router.get("/conversations", response_model=List[ConversationResponse])
async def get_conversations(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await chat_service.get_user_conversations(db, current_user.id)

@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(data: ConversationCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await chat_service.create_conversation(db, current_user.id, data)

@router.delete("/conversations/{id}")
async def delete_conversation(id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    success = await chat_service.delete_conversation(db, id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success"}

@router.get("/conversations/{id}/messages", response_model=List[MessageResponse])
async def get_messages(id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await chat_service.get_messages(db, id)

@router.post("/conversations/{id}/send")
async def send_message(id: int, data: ChatRequest, request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    async def event_generator():
        try:
            async for chunk in chat_service.send_message_stream(db, id, current_user.id, data.content):
                if await request.is_disconnected():
                    break
                yield {"data": chunk}
        except Exception as e:
            yield {"event": "error", "data": str(e)}
            
    return EventSourceResponse(event_generator())

@router.put("/conversations/{id}/model")
async def update_model(id: int, data: ModelUpdateRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import select
    from app.models.conversation import Conversation
    result = await db.execute(select(Conversation).where(Conversation.id == id, Conversation.user_id == current_user.id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.model_name = data.model_name
    await db.commit()
    return {"status": "success"}
