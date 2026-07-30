"""Database-free backend matching the current frontend API contract."""

from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from typing import Annotated, Literal

import httpx
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
    delete_chunks,
    drop_collection,
    embed_texts,
    embedding_config,
    extract_document,
    insert_chunks,
    list_chunks,
    split_text_by_tokens,
)
from app.knowledge_repository import (
    add_document_record,
    close_knowledge_database,
    create_knowledge_base_record,
    delete_knowledge_base_record,
    get_knowledge_base,
    init_knowledge_tables,
    list_documents,
    list_knowledge_bases,
    serialize_document,
    serialize_knowledge_base,
)
from app.rag.retriever import format_rag_prompt, retrieve_context

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def initial_token_usage() -> dict:
    timestamp = now_iso()
    return {
        "five_hour_token_limit": None,
        "weekly_token_limit": None,
        "five_hour_tokens_used": 0,
        "weekly_tokens_used": 0,
        "input_tokens_used": 0,
        "output_tokens_used": 0,
        "total_tokens_used": 0,
        "five_hour_window_started_at": timestamp,
        "weekly_window_started_at": timestamp,
    }


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
    await init_knowledge_tables()
    try:
        yield
    finally:
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

# Development-only state. It intentionally resets when the process restarts.
users: dict[int, dict] = {
    1: {
        "id": 1,
        "username": "admin",
        "email": "admin@example.com",
        "password": "admin123",
        "role": "admin",
        "is_root_admin": True,
        "is_active": True,
        "created_at": now_iso(),
        **initial_token_usage(),
    }
}
tokens: dict[str, int] = {}
login_attempts: dict[str, dict[str, float | int]] = {}
conversations: dict[int, dict] = {}
messages: dict[int, list[dict]] = {}
model_discovery_cache: dict[str, object] = {"expires_at": 0.0, "models": []}
user_ids = count(2)
conversation_ids = count(1)
message_ids = count(1)


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
            response = await client.get(
                f"{api_base}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
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


def refresh_token_windows(user: dict) -> None:
    defaults = initial_token_usage()
    for key, value in defaults.items():
        user.setdefault(key, value)

    now = datetime.now(timezone.utc)
    five_hour_start = datetime.fromisoformat(user["five_hour_window_started_at"])
    weekly_start = datetime.fromisoformat(user["weekly_window_started_at"])
    if now >= five_hour_start + timedelta(hours=5):
        user["five_hour_tokens_used"] = 0
        user["five_hour_window_started_at"] = now.isoformat()
    if now >= weekly_start + timedelta(days=7):
        user["weekly_tokens_used"] = 0
        user["weekly_window_started_at"] = now.isoformat()


def public_user(user: dict) -> User:
    refresh_token_windows(user)
    payload = {key: value for key, value in user.items() if key != "password"}
    five_hour_start = datetime.fromisoformat(user["five_hour_window_started_at"])
    weekly_start = datetime.fromisoformat(user["weekly_window_started_at"])
    payload["five_hour_resets_at"] = (five_hour_start + timedelta(hours=5)).isoformat()
    payload["weekly_resets_at"] = (weekly_start + timedelta(days=7)).isoformat()
    return User(**payload)


def enforce_token_quota(user: dict) -> None:
    refresh_token_windows(user)
    checks = [
        (
            "5 小时",
            user["five_hour_token_limit"],
            user["five_hour_tokens_used"],
            datetime.fromisoformat(user["five_hour_window_started_at"]) + timedelta(hours=5),
        ),
        (
            "周",
            user["weekly_token_limit"],
            user["weekly_tokens_used"],
            datetime.fromisoformat(user["weekly_window_started_at"]) + timedelta(days=7),
        ),
    ]
    now = datetime.now(timezone.utc)
    for label, limit, used, resets_at in checks:
        if limit is not None and used >= limit:
            retry_after = max(1, math.ceil((resets_at - now).total_seconds()))
            raise HTTPException(
                status_code=429,
                detail=f"已达到{label} Token 上限，请等待重置或联系管理员",
                headers={"Retry-After": str(retry_after)},
            )


def record_token_usage(user: dict, usage: dict) -> None:
    refresh_token_windows(user)
    input_tokens = max(0, int(usage.get("prompt_tokens") or 0))
    output_tokens = max(0, int(usage.get("completion_tokens") or 0))
    total_tokens = max(0, int(usage.get("total_tokens") or input_tokens + output_tokens))
    user["input_tokens_used"] += input_tokens
    user["output_tokens_used"] += output_tokens
    user["total_tokens_used"] += total_tokens
    user["five_hour_tokens_used"] += total_tokens
    user["weekly_tokens_used"] += total_tokens


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    return authorization.removeprefix("Bearer ").strip()


def current_user(token: Annotated[str, Depends(bearer_token)]) -> dict:
    user_id = tokens.get(token)
    user = users.get(user_id) if user_id else None
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="登录已失效")
    return user


def admin_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def owned_conversation(conversation_id: int, user: dict) -> dict:
    conversation = conversations.get(conversation_id)
    if not conversation or conversation["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


def public_message(message: dict) -> dict:
    """Keep ownership metadata server-side while returning the frontend shape."""
    return {key: value for key, value in message.items() if key != "user_id"}


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
            "users_and_chats": "memory",
            "knowledge_metadata": "mysql",
            "vectors": "milvus",
        },
    }


@app.post("/auth/token")
async def login(username: Annotated[str, Form()], password: Annotated[str, Form()]):
    now = time.time()
    attempt = login_attempts.get(username)
    if attempt:
        locked_until = float(attempt.get("locked_until", 0))
        if locked_until > now:
            retry_after = max(1, math.ceil(locked_until - now))
            raise HTTPException(
                status_code=429,
                detail="密码错误次数过多，请 5 分钟后再试",
                headers={"Retry-After": str(retry_after)},
            )
        if locked_until:
            login_attempts.pop(username, None)

    user = next((item for item in users.values() if item["username"] == username), None)
    if not user or user["password"] != password:
        attempt = login_attempts.setdefault(username, {"failures": 0, "locked_until": 0})
        attempt["failures"] = int(attempt["failures"]) + 1
        if int(attempt["failures"]) >= 3:
            attempt["locked_until"] = now + 300
            raise HTTPException(
                status_code=429,
                detail="密码错误次数过多，请 5 分钟后再试",
                headers={"Retry-After": "300"},
            )
        raise HTTPException(status_code=401, detail="密码错误")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="账户已停用")

    login_attempts.pop(username, None)
    token = secrets.token_urlsafe(32)
    tokens[token] = user["id"]
    return {"access_token": token, "token_type": "bearer", "user": public_user(user)}


@app.post("/auth/register", response_model=User)
async def register(data: RegisterRequest):
    if any(user["username"] == data.username for user in users.values()):
        raise HTTPException(status_code=409, detail="用户名已存在")
    if any(user["email"] == data.email for user in users.values()):
        raise HTTPException(status_code=409, detail="邮箱已存在")
    user_id = next(user_ids)
    user = {
        "id": user_id,
        "username": data.username,
        "email": data.email,
        "password": data.password,
        "role": "employee",
        "is_root_admin": False,
        "is_active": True,
        "created_at": now_iso(),
        **initial_token_usage(),
    }
    users[user_id] = user
    return public_user(user)


@app.get("/auth/me", response_model=User)
async def get_me(user: Annotated[dict, Depends(current_user)]):
    return public_user(user)


@app.get("/auth/users", response_model=list[User])
async def get_users(_: Annotated[dict, Depends(admin_user)]):
    return [public_user(user) for user in users.values()]


@app.put("/auth/users/{user_id}", response_model=User)
async def update_user(
    user_id: int,
    data: UserUpdate,
    operator: Annotated[dict, Depends(admin_user)],
):
    user = users.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    changed_fields = data.model_fields_set
    if user["is_root_admin"] and not operator["is_root_admin"] and changed_fields:
        raise HTTPException(status_code=403, detail="系统管理员账户不可修改")
    if "role" in changed_fields:
        if not operator["is_root_admin"]:
            raise HTTPException(status_code=403, detail="只有系统管理员可以修改用户身份")
        if user["is_root_admin"] and data.role != "admin":
            raise HTTPException(status_code=403, detail="系统管理员身份不可更改")
    if user["is_root_admin"] and "is_active" in changed_fields and data.is_active is not True:
        raise HTTPException(status_code=403, detail="系统管理员账户不可停用")

    for key in data.model_fields_set:
        user[key] = getattr(data, key)
    return public_user(user)


@app.post("/auth/users/{user_id}/token-usage/reset", response_model=User)
async def reset_user_token_usage(
    user_id: int,
    data: TokenUsageReset,
    _: Annotated[dict, Depends(admin_user)],
):
    user = users.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    timestamp = now_iso()
    if data.scope in {"five_hour", "all"}:
        user["five_hour_tokens_used"] = 0
        user["five_hour_window_started_at"] = timestamp
    if data.scope in {"weekly", "all"}:
        user["weekly_tokens_used"] = 0
        user["weekly_window_started_at"] = timestamp
    return public_user(user)


@app.get("/chat/conversations")
async def get_conversations(user: Annotated[dict, Depends(current_user)]):
    result = [
        {key: value for key, value in conversation.items() if key != "user_id"}
        for conversation in conversations.values()
        if conversation["user_id"] == user["id"]
    ]
    return sorted(result, key=lambda item: item["updated_at"], reverse=True)


@app.post("/chat/conversations")
async def create_conversation(data: ConversationCreate, user: Annotated[dict, Depends(current_user)]):
    if data.rag_enabled:
        if data.knowledge_base_id is None:
            raise HTTPException(status_code=422, detail="启用 RAG 前请选择知识库")
        if not await get_knowledge_base(data.knowledge_base_id):
            raise HTTPException(status_code=404, detail="知识库不存在")
    conversation_id = next(conversation_ids)
    timestamp = now_iso()
    conversation = {
        "id": conversation_id,
        "user_id": user["id"],
        "title": data.title,
        "model_name": data.model_name or default_model_id(),
        "knowledge_base_id": data.knowledge_base_id,
        "rag_enabled": data.rag_enabled,
        "retrieval_mode": data.retrieval_mode,
        "max_retrieval_tokens": data.max_retrieval_tokens,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    conversations[conversation_id] = conversation
    messages[conversation_id] = []
    return {key: value for key, value in conversation.items() if key != "user_id"}


@app.delete("/chat/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, user: Annotated[dict, Depends(current_user)]):
    owned_conversation(conversation_id, user)
    del conversations[conversation_id]
    messages.pop(conversation_id, None)
    return {"status": "success"}


@app.get("/chat/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int, user: Annotated[dict, Depends(current_user)]):
    owned_conversation(conversation_id, user)
    return [
        public_message(message)
        for message in messages.get(conversation_id, [])
        if message["user_id"] == user["id"]
    ]


@app.put("/chat/conversations/{conversation_id}/model")
async def update_conversation_model(
    conversation_id: int, data: ModelUpdate, user: Annotated[dict, Depends(current_user)]
):
    conversation = owned_conversation(conversation_id, user)
    conversation["model_name"] = data.model_name
    conversation["updated_at"] = now_iso()
    return {"status": "success", "model_name": data.model_name}


@app.put("/chat/conversations/{conversation_id}/rag")
async def update_conversation_rag(
    conversation_id: int,
    data: RagSettingsUpdate,
    user: Annotated[dict, Depends(current_user)],
):
    conversation = owned_conversation(conversation_id, user)
    if data.rag_enabled:
        if data.knowledge_base_id is None:
            raise HTTPException(status_code=422, detail="启用 RAG 前请选择知识库")
        if not await get_knowledge_base(data.knowledge_base_id):
            raise HTTPException(status_code=404, detail="知识库不存在")
    conversation["rag_enabled"] = data.rag_enabled
    conversation["knowledge_base_id"] = data.knowledge_base_id
    conversation["retrieval_mode"] = data.retrieval_mode
    conversation["max_retrieval_tokens"] = data.max_retrieval_tokens
    conversation["updated_at"] = now_iso()
    return {
        "status": "success",
        "rag_enabled": data.rag_enabled,
        "knowledge_base_id": data.knowledge_base_id,
        "retrieval_mode": data.retrieval_mode,
        "max_retrieval_tokens": data.max_retrieval_tokens,
    }


@app.post("/chat/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: int, data: ChatRequest, user: Annotated[dict, Depends(current_user)]
):
    conversation = owned_conversation(conversation_id, user)
    enforce_token_quota(user)

    conversation["rag_enabled"] = data.rag_enabled
    conversation["knowledge_base_id"] = data.knowledge_base_id
    conversation["retrieval_mode"] = data.retrieval_mode
    conversation["max_retrieval_tokens"] = data.max_retrieval_tokens
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

    messages[conversation_id].append(
        {
            "id": next(message_ids),
            "user_id": user["id"],
            "conversation_id": conversation_id,
            "role": "user",
            "content": data.content,
            "created_at": now_iso(),
        }
    )
    conversation["updated_at"] = now_iso()

    api_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("DASHSCOPE_API_KEY", "").strip()
    api_base = os.getenv("OPENAI_API_BASE", "").strip().rstrip("/")
    upstream_messages = [
        {"role": item["role"], "content": item["content"]}
        for item in messages[conversation_id][-20:]
        if item["user_id"] == user["id"] and item["role"] in {"user", "assistant", "system"}
    ]
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
                async with client.stream(
                    "POST",
                    f"{api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    },
                    json={
                        "model": conversation["model_name"],
                        "messages": upstream_messages,
                        "stream": True,
                        "stream_options": {"include_usage": True},
                    },
                ) as response:
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

            full_content = "".join(content_parts)
            if full_content:
                if token_usage:
                    record_token_usage(user, token_usage)
                messages[conversation_id].append(
                    {
                        "id": next(message_ids),
                        "user_id": user["id"],
                        "conversation_id": conversation_id,
                        "role": "assistant",
                        "content": full_content,
                        "created_at": now_iso(),
                        "rag_context": (
                            {
                                "enabled": True,
                                "knowledge_base_id": data.knowledge_base_id,
                                **retrieval,
                            }
                            if retrieval is not None
                            else None
                        ),
                    }
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
            created_by=user["id"],
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


@app.post("/knowledge-bases/{knowledge_base_id}/documents/")
async def upload_document(
    knowledge_base_id: int,
    user: Annotated[dict, Depends(admin_user)],
    file: Annotated[UploadFile, File()],
    chunk_tokens: Annotated[int, Form(ge=64, le=8192)] = 512,
    overlap_tokens: Annotated[int, Form(ge=0, le=4096)] = 64,
):
    knowledge_base = await get_knowledge_base(knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if overlap_tokens >= chunk_tokens:
        raise HTTPException(status_code=422, detail="Overlap 必须小于切片 Token 数")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > 30 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件不能超过 30 MB")

    file_name = file.filename or "未命名文件"
    primary_keys: list[int] = []
    try:
        text, source_type = await asyncio.to_thread(extract_document, file_name, content)
        chunks = await asyncio.to_thread(split_text_by_tokens, text, chunk_tokens, overlap_tokens)
        vectors = await embed_texts(
            [chunk["text"] for chunk in chunks], knowledge_base.vector_dimension
        )
        primary_keys = await asyncio.to_thread(
            insert_chunks,
            knowledge_base.collection_name,
            chunks,
            vectors,
            file_name,
            source_type,
            user["id"],
        )
        try:
            document = await add_document_record(
                knowledge_base_id=knowledge_base_id,
                name=file_name,
                size=len(content),
                content_type=file.content_type,
                source_type=source_type,
                chunk_tokens=chunk_tokens,
                overlap_tokens=overlap_tokens,
                chunk_count=len(primary_keys),
                total_tokens=sum(chunk["token_count"] for chunk in chunks),
                vector_dimension=knowledge_base.vector_dimension,
                embedding_model=knowledge_base.embedding_model,
            )
        except Exception:
            await asyncio.to_thread(
                delete_chunks, knowledge_base.collection_name, primary_keys
            )
            raise
    except EmbeddingServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except KnowledgeProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"文档向量化失败: {exc}") from exc

    return {"status": "success", "document": serialize_document(document)}


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
):
    knowledge_base = await get_knowledge_base(knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return await asyncio.to_thread(
            list_chunks, knowledge_base.collection_name, offset, limit
        )
    except KnowledgeProcessingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"读取 Milvus 切片失败: {exc}") from exc

@app.get("/models/")
async def get_models(refresh: bool = False):
    return await discover_models(refresh=refresh)
