"""FastAPI runtime backed by MySQL, Redis, Milvus, and OpenAI-compatible APIs."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import httpx
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from app.knowledge_runtime import (
    EmbeddingServiceError,
    KnowledgeProcessingError,
    collection_details,
    create_collection,
    drop_collection,
    embedding_config,
    list_chunks,
)
from app.knowledge_repository import (
    close_knowledge_database,
    create_knowledge_base_record,
    delete_knowledge_base_record,
    get_knowledge_base,
    list_documents,
    list_knowledge_bases,
    serialize_document,
    serialize_knowledge_base,
)
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    token_fingerprint,
    verify_password,
    verify_token,
)
from app.db.redis import close_redis, redis_client
from app.document_tasks import (
    create_task as create_document_task,
    document_worker,
    enqueue_task,
    get_task as get_document_task_record,
    save_upload,
    serialize_task,
)
from app.rag.retriever import format_rag_prompt, retrieve_context
from app.state_repository import (
    add_message,
    create_conversation_record,
    create_user,
    delete_owned_conversation,
    get_owned_conversation,
    get_user,
    get_user_by_username,
    init_state_tables,
    list_conversations,
    list_messages,
    list_users,
    quota_state,
    record_token_usage,
    reset_user_usage,
    serialize_conversation,
    serialize_message,
    serialize_user,
    update_owned_conversation,
    update_user_fields,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class TransientUpstreamError(RuntimeError):
    pass

class User(BaseModel):
    id: int
    username: str
    email: str
    role: Literal["admin", "employee"] = "employee"
    is_root_admin: bool = False
    is_active: bool = True
    created_at: str
    five_hour_token_limit: int | None = None
    weekly_token_limit: int | None = None
    five_hour_tokens_used: int = 0
    weekly_tokens_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    total_tokens_used: int = 0
    five_hour_window_started_at: str
    weekly_window_started_at: str
    five_hour_resets_at: str
    weekly_resets_at: str


class RegisterRequest(BaseModel):
    model_config = {"extra": "forbid"}

    username: str = Field(min_length=2, max_length=50)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=6)


class UserUpdate(BaseModel):
    role: Literal["admin", "employee"] | None = None
    is_active: bool | None = None
    five_hour_token_limit: int | None = Field(default=None, ge=1)
    weekly_token_limit: int | None = Field(default=None, ge=1)


class TokenUsageReset(BaseModel):
    scope: Literal["five_hour", "weekly", "all"]


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class ConversationCreate(BaseModel):
    title: str = "新对话"
    model_name: str | None = None
    knowledge_base_id: int | None = None
    rag_enabled: bool = False
    retrieval_mode: Literal["semantic", "dense", "hybrid"] = "semantic"
    max_retrieval_tokens: int = Field(default=2048, ge=128, le=16000)


class ModelUpdate(BaseModel):
    model_name: str


class ChatRequest(BaseModel):
    content: str = Field(min_length=1)
    rag_enabled: bool = False
    knowledge_base_id: int | None = None
    retrieval_mode: Literal["semantic", "dense", "hybrid"] = "semantic"
    max_retrieval_tokens: int = Field(default=2048, ge=128, le=16000)


class RagSettingsUpdate(BaseModel):
    rag_enabled: bool
    knowledge_base_id: int | None = None
    retrieval_mode: Literal["semantic", "dense", "hybrid"] = "semantic"
    max_retrieval_tokens: int = Field(default=2048, ge=128, le=16000)


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = ""
    vector_dimension: int = Field(default=1024, ge=64, le=4096)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_state_tables()
    worker_stop = asyncio.Event()
    worker = asyncio.create_task(document_worker(worker_stop))
    try:
        yield
    finally:
        worker_stop.set()
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        await close_redis()
        await close_knowledge_database()


app = FastAPI(
    title="智能 RAG 系统（MySQL + Milvus 开发版）",
    version="0.3.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model_discovery_cache: dict[str, object] = {"expires_at": 0.0, "models": []}


def configured_model_ids() -> list[str]:
    """Read public model identifiers from environment configuration."""
    configured = os.getenv("AVAILABLE_MODELS", "")
    model_ids = [model.strip() for model in configured.split(",") if model.strip()]
    default_model = os.getenv("DEFAULT_MODEL", "").strip()
    if default_model and default_model not in model_ids:
        model_ids.insert(0, default_model)
    return model_ids or ["local-demo"]


def default_model_id() -> str:
    return os.getenv("DEFAULT_MODEL", "").strip() or configured_model_ids()[0]


def configured_provider() -> str:
    explicit_provider = os.getenv("MODEL_PROVIDER", "").strip()
    if explicit_provider:
        return explicit_provider
    api_base = os.getenv("OPENAI_API_BASE", "").lower()
    if "dashscope" in api_base or "aliyuncs" in api_base:
        return "DashScope"
    if "openai.com" in api_base:
        return "OpenAI"
    return "OpenAI Compatible"


NON_CHAT_MODEL_KEYWORDS = {
    "embedding",
    "rerank",
    "image",
    "audio",
    "realtime",
    "speech",
    "tts",
    "asr",
    "ocr",
    "video",
    "moderation",
    "safety",
}


def is_chat_model(model_id: str) -> bool:
    """Exclude model families that clearly do not use Chat Completions."""
    lowered = model_id.lower()
    return not any(keyword in lowered for keyword in NON_CHAT_MODEL_KEYWORDS)


def model_response(model_ids: list[str], source: str) -> list[dict]:
    default_model = default_model_id()
    unique_ids = list(dict.fromkeys(model_ids))
    if default_model in unique_ids:
        unique_ids.remove(default_model)
    unique_ids.sort(key=str.lower)
    if default_model in model_ids:
        unique_ids.insert(0, default_model)
    provider = configured_provider()
    return [
        {
            "id": model_id,
            "name": model_id,
            "description": (
                "后端 .env 默认模型"
                if model_id == default_model
                else f"通过 {source} 自动发现"
            ),
            "provider": provider,
        }
        for model_id in unique_ids
    ]


async def discover_models(refresh: bool = False) -> list[dict]:
    now = time.time()
    cached_models = model_discovery_cache["models"]
    if not refresh and cached_models and float(model_discovery_cache["expires_at"]) > now:
        return cached_models  # type: ignore[return-value]

    api_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("DASHSCOPE_API_KEY", "").strip()
    api_base = os.getenv("OPENAI_API_BASE", "").strip().rstrip("/")
    explicit_models = [
        model.strip()
        for model in os.getenv("AVAILABLE_MODELS", "").split(",")
        if model.strip()
    ]

    try:
        if not api_key or not api_base:
            raise RuntimeError("模型服务 URL 或 API Key 未配置")
        async with httpx.AsyncClient(timeout=20.0) as client:
            response: httpx.Response | None = None
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
                retry=retry_if_exception_type(
                    (httpx.TransportError, TransientUpstreamError)
                ),
                reraise=True,
            ):
                with attempt:
                    response = await client.get(
                        f"{api_base}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise TransientUpstreamError(
                            f"模型发现服务暂时不可用: {response.status_code}"
                        )
            assert response is not None
            response.raise_for_status()
            payload = response.json()

        discovered_ids = [
            item.get("id", "").strip()
            for item in payload.get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        discovered_ids = [model_id for model_id in discovered_ids if model_id and is_chat_model(model_id)]
        if explicit_models:
            allowlist = set(explicit_models) | {default_model_id()}
            discovered_ids = [model_id for model_id in discovered_ids if model_id in allowlist]
        if not discovered_ids:
            raise RuntimeError("模型列表中没有可用于聊天的模型")
        models = model_response(discovered_ids, "/models")
    except (httpx.HTTPError, ValueError, RuntimeError):
        models = model_response(configured_model_ids(), ".env")

    model_discovery_cache["models"] = models
    model_discovery_cache["expires_at"] = now + 300
    return models


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    return authorization.removeprefix("Bearer ").strip()


async def current_user(token: Annotated[str, Depends(bearer_token)]):
    try:
        payload = verify_token(token, "access")
        user_id = int(payload["sub"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="登录已失效")
    user = await get_user(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="登录已失效")
    return user


def admin_user(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "智能 RAG 系统 MySQL + Milvus 开发版运行中",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "storage": {
            "users_and_chats": "mysql",
            "login_security": "redis",
            "knowledge_metadata": "mysql",
            "vectors": "milvus",
        },
    }


@app.post("/auth/token")
async def login(username: Annotated[str, Form()], password: Annotated[str, Form()]):
    normalized_username = username.strip()
    failure_key = f"auth:failures:{normalized_username}"
    lock_key = f"auth:lock:{normalized_username}"
    try:
        retry_after = await redis_client.ttl(lock_key)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="登录安全服务暂不可用") from exc
    if retry_after > 0:
        raise HTTPException(
            status_code=429,
            detail="密码错误次数过多，请 5 分钟后再试",
            headers={"Retry-After": str(retry_after)},
        )

    user = await get_user_by_username(normalized_username)
    if not user or not verify_password(password, user.hashed_password):
        try:
            failures = await redis_client.incr(failure_key)
            if failures == 1:
                await redis_client.expire(failure_key, 300)
            if failures >= 3:
                pipeline = redis_client.pipeline(transaction=True)
                pipeline.set(lock_key, "1", ex=300)
                pipeline.delete(failure_key)
                await pipeline.execute()
                raise HTTPException(
                    status_code=429,
                    detail="密码错误次数过多，请 5 分钟后再试",
                    headers={"Retry-After": "300"},
                )
        except RedisError as exc:
            raise HTTPException(status_code=503, detail="登录安全服务暂不可用") from exc
        raise HTTPException(status_code=401, detail="密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已停用")

    access_token = create_access_token(user.id, user.username)
    refresh_token, refresh_id = create_refresh_token(user.id, user.username)
    try:
        pipeline = redis_client.pipeline(transaction=True)
        pipeline.delete(failure_key, lock_key)
        pipeline.set(
            f"auth:refresh:{refresh_id}",
            token_fingerprint(refresh_token),
            ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        )
        await pipeline.execute()
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="登录安全服务暂不可用") from exc
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": serialize_user(user),
    }


@app.post("/auth/refresh")
async def refresh_access_token(data: RefreshTokenRequest):
    try:
        payload = verify_token(data.refresh_token, "refresh")
        refresh_id = str(payload["jti"])
        user_id = int(payload["sub"])
        expected = await redis_client.get(f"auth:refresh:{refresh_id}")
    except (ValueError, TypeError, RedisError) as exc:
        raise HTTPException(status_code=401, detail="Refresh Token 无效或已过期") from exc
    if not expected or expected != token_fingerprint(data.refresh_token):
        raise HTTPException(status_code=401, detail="Refresh Token 无效或已过期")
    user = await get_user(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="账户不存在或已停用")
    return {
        "access_token": create_access_token(user.id, user.username),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@app.post("/auth/logout")
async def logout(data: RefreshTokenRequest):
    try:
        payload = verify_token(data.refresh_token, "refresh")
        await redis_client.delete(f"auth:refresh:{payload['jti']}")
    except (ValueError, RedisError):
        pass
    return {"status": "success"}


@app.post("/auth/register", response_model=User)
async def register(data: RegisterRequest):
    try:
        user = await create_user(
            username=data.username.strip(),
            email=data.email.strip().lower(),
            hashed_password=hash_password(data.password),
        )
    except IntegrityError as exc:
        message = str(exc.orig).lower()
        detail = "邮箱已存在" if "email" in message else "用户名已存在"
        raise HTTPException(status_code=409, detail=detail) from exc
    return serialize_user(user)


@app.get("/auth/me", response_model=User)
async def get_me(user=Depends(current_user)):
    return serialize_user(user)


@app.get("/auth/users", response_model=list[User])
async def get_users(_: Annotated[object, Depends(admin_user)]):
    return [serialize_user(user) for user in await list_users()]


@app.put("/auth/users/{user_id}", response_model=User)
async def update_user(
    user_id: int,
    data: UserUpdate,
    operator=Depends(admin_user),
):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    changed_fields = data.model_fields_set
    if "role" in changed_fields and data.role is None:
        raise HTTPException(status_code=422, detail="用户身份不能为 null")
    if "is_active" in changed_fields and data.is_active is None:
        raise HTTPException(status_code=422, detail="账户状态不能为 null")
    if user.is_root_admin and not operator.is_root_admin and changed_fields:
        raise HTTPException(status_code=403, detail="系统管理员账户不可修改")
    if "role" in changed_fields:
        if not operator.is_root_admin:
            raise HTTPException(status_code=403, detail="只有系统管理员可以修改用户身份")
        if user.is_root_admin and data.role != "admin":
            raise HTTPException(status_code=403, detail="系统管理员身份不可更改")
    if user.is_root_admin and "is_active" in changed_fields and data.is_active is not True:
        raise HTTPException(status_code=403, detail="系统管理员账户不可停用")

    updated = await update_user_fields(
        user_id, {key: getattr(data, key) for key in changed_fields}
    )
    return serialize_user(updated)


@app.post("/auth/users/{user_id}/token-usage/reset", response_model=User)
async def reset_user_token_usage(
    user_id: int,
    data: TokenUsageReset,
    _: Annotated[object, Depends(admin_user)],
):
    user = await reset_user_usage(user_id, data.scope)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return serialize_user(user)


@app.get("/chat/conversations")
async def get_conversations(user=Depends(current_user)):
    return [
        serialize_conversation(item) for item in await list_conversations(user.id)
    ]


@app.post("/chat/conversations")
async def create_conversation(data: ConversationCreate, user=Depends(current_user)):
    if data.rag_enabled:
        if data.knowledge_base_id is None:
            raise HTTPException(status_code=422, detail="启用 RAG 前请选择知识库")
        if not await get_knowledge_base(data.knowledge_base_id):
            raise HTTPException(status_code=404, detail="知识库不存在")
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


@app.delete("/chat/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, user=Depends(current_user)):
    if not await delete_owned_conversation(conversation_id, user.id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "success"}


@app.get("/chat/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int, user=Depends(current_user)):
    if not await get_owned_conversation(conversation_id, user.id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return [
        serialize_message(message) for message in await list_messages(conversation_id)
    ]


@app.put("/chat/conversations/{conversation_id}/model")
async def update_conversation_model(
    conversation_id: int, data: ModelUpdate, user=Depends(current_user)
):
    conversation = await update_owned_conversation(
        conversation_id, user.id, {"model_name": data.model_name}
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "success", "model_name": data.model_name}


@app.put("/chat/conversations/{conversation_id}/rag")
async def update_conversation_rag(
    conversation_id: int,
    data: RagSettingsUpdate,
    user=Depends(current_user),
):
    conversation = await get_owned_conversation(conversation_id, user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    if data.rag_enabled:
        if data.knowledge_base_id is None:
            raise HTTPException(status_code=422, detail="启用 RAG 前请选择知识库")
        if not await get_knowledge_base(data.knowledge_base_id):
            raise HTTPException(status_code=404, detail="知识库不存在")
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


@app.post("/chat/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: int, data: ChatRequest, user=Depends(current_user)
):
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
    retrieval: dict | None = None
    if data.rag_enabled:
        if data.knowledge_base_id is None:
            raise HTTPException(status_code=422, detail="启用 RAG 前请选择知识库")
        knowledge_base = await get_knowledge_base(data.knowledge_base_id)
        if not knowledge_base:
            raise HTTPException(status_code=404, detail="知识库不存在")
        try:
            retrieval = await retrieve_context(
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

    history = await list_messages(conversation_id)
    await add_message(
        conversation_id=conversation_id,
        role="user",
        content=data.content,
    )

    api_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("DASHSCOPE_API_KEY", "").strip()
    api_base = os.getenv("OPENAI_API_BASE", "").strip().rstrip("/")
    upstream_messages = [
        {"role": item.role, "content": item.content}
        for item in history[-19:]
        if item.role in {"user", "assistant", "system"}
    ]
    upstream_messages.append({"role": "user", "content": data.content})
    if retrieval is not None:
        upstream_messages.insert(
            0,
            {"role": "system", "content": format_rag_prompt(retrieval)},
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
            if not api_key:
                raise RuntimeError("后端未配置 OPENAI_API_KEY 或 DASHSCOPE_API_KEY")
            if not api_base:
                raise RuntimeError("后端未配置 OPENAI_API_BASE")

            timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                request = client.build_request(
                    "POST",
                    f"{api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    },
                    json={
                        "model": conversation.model_name,
                        "messages": upstream_messages,
                        "stream": True,
                        "stream_options": {"include_usage": True},
                    },
                )
                response: httpx.Response | None = None
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(3),
                    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
                    retry=retry_if_exception_type(
                        (httpx.TransportError, TransientUpstreamError)
                    ),
                    reraise=True,
                ):
                    with attempt:
                        response = await client.send(request, stream=True)
                        if response.status_code == 429 or response.status_code >= 500:
                            await response.aread()
                            await response.aclose()
                            raise TransientUpstreamError(
                                f"模型服务暂时不可用: {response.status_code}"
                            )
                assert response is not None
                try:
                    if response.status_code >= 400:
                        await response.aread()
                        try:
                            error_payload = response.json()
                            detail = error_payload.get("error", {}).get("message") or response.text
                        except (ValueError, AttributeError):
                            detail = response.text
                        raise RuntimeError(f"模型服务返回 {response.status_code}: {detail[:500]}")

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line.removeprefix("data:").strip()
                        if not payload or payload == "[DONE]":
                            continue
                        try:
                            upstream_chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if upstream_chunk.get("usage"):
                            token_usage.update(upstream_chunk["usage"])
                        choices = upstream_chunk.get("choices") or []
                        if not choices:
                            continue
                        content = choices[0].get("delta", {}).get("content")
                        if not content:
                            continue
                        content_parts.append(content)
                        yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
                finally:
                    await response.aclose()

            full_content = "".join(content_parts)
            if full_content:
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
            else:
                raise RuntimeError("模型流已结束，但没有返回可显示的文本")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_message = str(exc) or "模型调用失败"
            yield f"event: error\ndata: {json.dumps({'message': error_message}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/knowledge-bases/embedding-config")
async def get_embedding_config(_: Annotated[dict, Depends(current_user)]):
    return embedding_config()


@app.get("/knowledge-bases/")
async def get_knowledge_bases(_: Annotated[dict, Depends(current_user)]):
    items = await list_knowledge_bases()
    return [serialize_knowledge_base(item) for item in items]


@app.post("/knowledge-bases/")
async def create_knowledge_base(
    data: KnowledgeBaseCreate, user: Annotated[dict, Depends(admin_user)]
):
    config = embedding_config()
    if data.vector_dimension not in config["supported_dimensions"]:
        raise HTTPException(
            status_code=422,
            detail=f"当前向量模型支持的维度为: {config['supported_dimensions']}",
        )
    collection_name = f"kb_{uuid.uuid4().hex}"
    try:
        await asyncio.to_thread(create_collection, collection_name, data.vector_dimension)
        knowledge_base = await create_knowledge_base_record(
            name=data.name,
            description=data.description or "",
            collection_name=collection_name,
            embedding_model=config["model"],
            vector_dimension=data.vector_dimension,
            created_by=user.id,
        )
    except Exception as exc:
        try:
            await asyncio.to_thread(drop_collection, collection_name)
        except Exception:
            pass
        raise HTTPException(status_code=503, detail=f"创建 Milvus 集合失败: {exc}") from exc
    return serialize_knowledge_base(knowledge_base)


@app.delete("/knowledge-bases/{knowledge_base_id}")
async def delete_knowledge_base(
    knowledge_base_id: int, _: Annotated[dict, Depends(admin_user)]
):
    knowledge_base = await get_knowledge_base(knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        await asyncio.to_thread(drop_collection, knowledge_base.collection_name)
        await delete_knowledge_base_record(knowledge_base_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"删除 Milvus 集合失败: {exc}") from exc
    return {"status": "success"}


@app.post("/knowledge-bases/{knowledge_base_id}/documents/", status_code=202)
async def upload_document(
    knowledge_base_id: int,
    file: Annotated[UploadFile, File()],
    chunk_tokens: Annotated[int, Form(ge=64, le=8192)] = 512,
    overlap_tokens: Annotated[int, Form(ge=0, le=4096)] = 64,
    user=Depends(admin_user),
):
    knowledge_base = await get_knowledge_base(knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if overlap_tokens >= chunk_tokens:
        raise HTTPException(status_code=422, detail="Overlap 必须小于切片 Token 数")

    file_name = file.filename or "未命名文件"
    task_id = str(uuid.uuid4())
    try:
        temp_path, file_size = await save_upload(file, task_id)
        task = await create_document_task(
            task_id=task_id,
            knowledge_base_id=knowledge_base_id,
            created_by=user.id,
            file_name=file_name,
            content_type=file.content_type,
            file_size=file_size,
            temp_path=str(temp_path),
            chunk_tokens=chunk_tokens,
            overlap_tokens=overlap_tokens,
        )
        await enqueue_task(task.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="文档任务队列暂不可用") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"创建文档任务失败: {exc}") from exc

    return {"status": "queued", "task": serialize_task(task)}


@app.get("/knowledge-bases/tasks/{task_id}")
async def get_document_task(task_id: str, user=Depends(current_user)):
    task = await get_document_task_record(
        task_id, user.id, is_admin=user.role == "admin"
    )
    if task is None:
        raise HTTPException(status_code=404, detail="文档任务不存在")
    return serialize_task(task)


@app.get("/knowledge-bases/{knowledge_base_id}/documents/")
async def get_documents(
    knowledge_base_id: int, _: Annotated[dict, Depends(current_user)]
):
    if not await get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    items = await list_documents(knowledge_base_id)
    return [serialize_document(item) for item in items]


@app.get("/knowledge-bases/{knowledge_base_id}/milvus/schema")
async def get_milvus_schema(
    knowledge_base_id: int, _: Annotated[dict, Depends(current_user)]
):
    knowledge_base = await get_knowledge_base(knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return await asyncio.to_thread(collection_details, knowledge_base.collection_name)
    except KnowledgeProcessingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"读取 Milvus 字段失败: {exc}") from exc


@app.get("/knowledge-bases/{knowledge_base_id}/milvus/chunks")
async def get_milvus_chunks(
    knowledge_base_id: int,
    _: Annotated[dict, Depends(current_user)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[int | None, Query(ge=0)] = None,
):
    knowledge_base = await get_knowledge_base(knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return await asyncio.to_thread(
            list_chunks, knowledge_base.collection_name, offset, limit, cursor
        )
    except KnowledgeProcessingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"读取 Milvus 切片失败: {exc}") from exc

@app.get("/models/")
async def get_models(refresh: bool = False):
    return await discover_models(refresh=refresh)
