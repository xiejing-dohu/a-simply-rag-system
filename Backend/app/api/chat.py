"""对话会话管理、RAG 设置与 SSE 流式对话路由模块

包含对话 CRUD、消息历史列表查询、模型/RAG 检索配置更新以及基于 SSE 流式事件的 RAG 聊天接口。
"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.dependencies import current_user
from app.knowledge_repository import get_knowledge_base
from app.knowledge_runtime import EmbeddingServiceError
from app.rag.retriever import format_rag_prompt, retrieve_context
from app.schemas.chat import (
    ChatRequest,
    ConversationCreate,
    ModelUpdate,
    RagSettingsUpdate,
)
from app.services.chat_completion import stream_chat_completion
from app.services.model_catalog import default_model_id
from app.state_repository import (
    add_message,
    create_conversation_record,
    delete_owned_conversation,
    get_owned_conversation,
    list_conversations,
    list_messages,
    quota_state,
    record_token_usage,
    serialize_conversation,
    serialize_message,
    update_owned_conversation,
)

router = APIRouter(prefix="/chat", tags=["聊天"])


async def _validate_rag_settings(
    rag_enabled: bool, knowledge_base_id: int | None
) -> None:
    """校验开启 RAG 时的知识库合法性"""
    if not rag_enabled:
        return
    if knowledge_base_id is None:
        raise HTTPException(status_code=422, detail="启用 RAG 前请选择知识库")
    if not await get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=404, detail="知识库不存在")


@router.get("/conversations")
async def get_conversations(user=Depends(current_user)):
    """获取当前已登录用户的全部对话会话列表"""
    return [
        serialize_conversation(item) for item in await list_conversations(user.id)
    ]


@router.post("/conversations")
async def create_conversation(data: ConversationCreate, user=Depends(current_user)):
    """创建新的对话会话"""
    await _validate_rag_settings(data.rag_enabled, data.knowledge_base_id)
    conversation = await create_conversation_record(
        user_id=user.id,
        title=data.title,
        model_name=data.model_name or default_model_id(),
        knowledge_base_id=data.knowledge_base_id,
        rag_enabled=data.rag_enabled,
        retrieval_mode=data.retrieval_mode,
        max_retrieval_tokens=data.max_retrieval_tokens,
    )
    return serialize_conversation(conversation)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, user=Depends(current_user)):
    """删除指定的对话会话及其全部历史消息"""
    if not await delete_owned_conversation(conversation_id, user.id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "success"}


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int, user=Depends(current_user)):
    """获取某个对话会话下的历史消息记录列表"""
    if not await get_owned_conversation(conversation_id, user.id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return [
        serialize_message(message) for message in await list_messages(conversation_id)
    ]


@router.put("/conversations/{conversation_id}/model")
async def update_conversation_model(
    conversation_id: int, data: ModelUpdate, user=Depends(current_user)
):
    """修改对话会话调用的 LLM 大模型"""
    conversation = await update_owned_conversation(
        conversation_id, user.id, {"model_name": data.model_name}
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "success", "model_name": data.model_name}


@router.put("/conversations/{conversation_id}/rag")
async def update_conversation_rag(
    conversation_id: int,
    data: RagSettingsUpdate,
    user=Depends(current_user),
):
    """更新对话会话的 RAG 检索参数设置"""
    if not await get_owned_conversation(conversation_id, user.id):
        raise HTTPException(status_code=404, detail="会话不存在")
    await _validate_rag_settings(data.rag_enabled, data.knowledge_base_id)
    await update_owned_conversation(
        conversation_id,
        user.id,
        {
            "rag_enabled": data.rag_enabled,
            "knowledge_base_id": data.knowledge_base_id,
            "retrieval_mode": data.retrieval_mode,
            "max_retrieval_tokens": data.max_retrieval_tokens,
        },
    )
    return {
        "status": "success",
        "rag_enabled": data.rag_enabled,
        "knowledge_base_id": data.knowledge_base_id,
        "retrieval_mode": data.retrieval_mode,
        "max_retrieval_tokens": data.max_retrieval_tokens,
    }


async def _retrieve_for_request(data: ChatRequest) -> dict | None:
    """根据聊天请求尝试在 Milvus 向量知识库中检索上下文"""
    if not data.rag_enabled:
        return None
    if data.knowledge_base_id is None:
        raise HTTPException(status_code=422, detail="启用 RAG 前请选择知识库")
    knowledge_base = await get_knowledge_base(data.knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return await retrieve_context(
            collection_name=knowledge_base.collection_name,
            query_text=data.content,
            vector_dimension=knowledge_base.vector_dimension,
            mode=data.retrieval_mode,
            max_tokens=data.max_retrieval_tokens,
        )
    except EmbeddingServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"RAG 检索失败: {exc}") from exc


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: int, data: ChatRequest, user=Depends(current_user)
):
    """核心流式聊天接口：包含额度校验、RAG 检索注入、SSE Chunk 推送与 Token 消耗自动统计"""
    conversation = await get_owned_conversation(conversation_id, user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    _, retry_after = await quota_state(user.id)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="已达到 Token 上限，请等待重置或联系管理员",
            headers={"Retry-After": str(retry_after)},
        )

    await _validate_rag_settings(data.rag_enabled, data.knowledge_base_id)
    conversation = await update_owned_conversation(
        conversation_id,
        user.id,
        {
            "rag_enabled": data.rag_enabled,
            "knowledge_base_id": data.knowledge_base_id,
            "retrieval_mode": data.retrieval_mode,
            "max_retrieval_tokens": data.max_retrieval_tokens,
        },
    )
    retrieval = await _retrieve_for_request(data)
    history = await list_messages(conversation_id)
    await add_message(conversation_id=conversation_id, role="user", content=data.content)

    upstream_messages = [
        {"role": item.role, "content": item.content}
        for item in history[-19:]
        if item.role in {"user", "assistant", "system"}
    ]
    upstream_messages.append({"role": "user", "content": data.content})
    if retrieval is not None:
        upstream_messages.insert(
            0, {"role": "system", "content": format_rag_prompt(retrieval)}
        )

    async def event_stream():
        content_parts: list[str] = []
        token_usage: dict = {}
        try:
            if retrieval is not None:
                rag_payload = {
                    "enabled": True,
                    "knowledge_base_id": data.knowledge_base_id,
                    **retrieval,
                }
                yield (
                    "event: rag\n"
                    f"data: {json.dumps(rag_payload, ensure_ascii=False)}\n\n"
                )

            async for event in stream_chat_completion(
                model_name=conversation.model_name,
                messages=upstream_messages,
            ):
                if event["type"] == "usage":
                    token_usage.update(event["usage"])
                    continue
                content = event["content"]
                content_parts.append(content)
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"

            full_content = "".join(content_parts)
            if not full_content:
                raise RuntimeError("模型流已结束，但没有返回可显示的文本")
            if token_usage:
                await record_token_usage(user.id, token_usage)
            await add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_content,
                rag_context=(
                    {
                        "enabled": True,
                        "knowledge_base_id": data.knowledge_base_id,
                        **retrieval,
                    }
                    if retrieval is not None
                    else None
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = str(exc) or "模型调用失败"
            yield f"event: error\ndata: {json.dumps({'message': message}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
