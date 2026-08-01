"""模型发现与目录管理服务模块

自动从 OpenAI 兼容 API (/v1/models) 获取可用对话模型列表，
支持非 Chat 模型的关键词过滤、提供商识别以及本地缓存机制（5分钟过期）。
"""

import os
import time

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.exceptions import TransientUpstreamError

# 内存缓存，避免频繁请求上游 API
_cache: dict[str, object] = {"expires_at": 0.0, "models": []}

# 排除非对话模型的关键词表
_non_chat_keywords = {
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


def configured_model_ids() -> list[str]:
    """获取环境变量配置的模型标识列表

    Returns:
        list[str]: 包含 AVAILABLE_MODELS 与 DEFAULT_MODEL 的配置列表
    """
    configured = os.getenv("AVAILABLE_MODELS", "")
    model_ids = [model.strip() for model in configured.split(",") if model.strip()]
    default_model = os.getenv("DEFAULT_MODEL", "").strip()
    if default_model and default_model not in model_ids:
        model_ids.insert(0, default_model)
    return model_ids or ["local-demo"]


def default_model_id() -> str:
    """获取系统默认设定的模型标识

    Returns:
        str: 默认模型 ID
    """
    return os.getenv("DEFAULT_MODEL", "").strip() or configured_model_ids()[0]


def _configured_provider() -> str:
    """自动判断模型的提供商来源（如 DashScope, OpenAI 等）

    Returns:
        str: 提供商名称
    """
    explicit_provider = os.getenv("MODEL_PROVIDER", "").strip()
    if explicit_provider:
        return explicit_provider
    api_base = os.getenv("OPENAI_API_BASE", "").lower()
    if "dashscope" in api_base or "aliyuncs" in api_base:
        return "DashScope"
    if "openai.com" in api_base:
        return "OpenAI"
    return "OpenAI Compatible"


def _is_chat_model(model_id: str) -> bool:
    """判断给定的模型 ID 是否为文本对话模型

    Args:
        model_id (str): 模型标识字符串

    Returns:
        bool: 是对话模型返回 True，包含 Embedding/Rerank 等关键词时返回 False
    """
    lowered = model_id.lower()
    return not any(keyword in lowered for keyword in _non_chat_keywords)


def _model_response(model_ids: list[str], source: str) -> list[dict]:
    """格式化组装模型元数据列表

    Args:
        model_ids (list[str]): 模型 ID 列表
        source (str): 模型来源标识描述

    Returns:
        list[dict]: 格式化后的模型列表字典
    """
    default_model = default_model_id()
    unique_ids = list(dict.fromkeys(model_ids))
    if default_model in unique_ids:
        unique_ids.remove(default_model)
    unique_ids.sort(key=str.lower)
    if default_model in model_ids:
        unique_ids.insert(0, default_model)
    provider = _configured_provider()
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
    """动态获取可用大语言模型列表

    从上游 OpenAI 兼容 `/models` 接口获取模型，过滤对话模型，
    如果接口失败则退回到环境变量配置的模型列表，并进行 5 分钟缓存。

    Args:
        refresh (bool): 是否强制忽略缓存刷新列表

    Returns:
        list[dict]: 模型描述字典列表
    """
    now = time.time()
    cached_models = _cache["models"]
    if not refresh and cached_models and float(_cache["expires_at"]) > now:
        return cached_models  # type: ignore[return-value]

    api_key = (
        os.getenv("OPENAI_API_KEY", "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
    )
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
        discovered_ids = [
            model_id
            for model_id in discovered_ids
            if model_id and _is_chat_model(model_id)
        ]
        if explicit_models:
            allowlist = set(explicit_models) | {default_model_id()}
            discovered_ids = [
                model_id for model_id in discovered_ids if model_id in allowlist
            ]
        if not discovered_ids:
            raise RuntimeError("模型列表中没有可用于聊天的模型")
        models = _model_response(discovered_ids, "/models")
    except (httpx.HTTPError, ValueError, RuntimeError):
        models = _model_response(configured_model_ids(), ".env")

    _cache["models"] = models
    _cache["expires_at"] = now + 300
    return models
