"""OpenAI 兼容接口的对话流式输出服务模块

支持 SSE (Server-Sent Events) 流式推送大模型生成内容及 Token 消耗统计数据，
并内置 Tenacity 指数退避重试逻辑。
"""

from collections.abc import AsyncIterator
import json
import os
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.exceptions import TransientUpstreamError


async def stream_chat_completion(
    *, model_name: str, messages: list[dict[str, str]]
) -> AsyncIterator[dict[str, Any]]:
    """向 LLM 发起流式对话请求并异步 yield 消息 Chunk

    Args:
        model_name (str): 调用的模型标识名称
        messages (list[dict[str, str]]): 历史上下文与当前用户消息列表

    Yields:
        AsyncIterator[dict[str, Any]]:
            - {"type": "content", "content": "...": 流式文本增量块
            - {"type": "usage", "usage": {...}}: 包含 token 统计信息的字典

    Raises:
        RuntimeError: 当缺失 API 配置或上游返回 4xx/5xx 错误时抛出。
    """
    api_key = (
        os.getenv("OPENAI_API_KEY", "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
    )
    api_base = os.getenv("OPENAI_API_BASE", "").strip().rstrip("/")
    if not api_key:
        raise RuntimeError("后端未配置 OPENAI_API_KEY 或 DASHSCOPE_API_KEY")
    if not api_base:
        raise RuntimeError("后端未配置 OPENAI_API_BASE")

    # 配置 HTTP 客户端超时时间
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
                "model": model_name,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
        response: httpx.Response | None = None
        # 使用 Tenacity 重试 5xx / 429 暂态错误
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
                    payload = response.json()
                    detail = payload.get("error", {}).get("message") or response.text
                except (ValueError, AttributeError):
                    detail = response.text
                raise RuntimeError(
                    f"模型服务返回 {response.status_code}: {detail[:500]}"
                )

            # 解析 SSE 流式响应
            async for line in response.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload_text = line.removeprefix("data:").strip()
                if not payload_text or payload_text == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    yield {"type": "usage", "usage": chunk["usage"]}
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content")
                if content:
                    yield {"type": "content", "content": content}
        finally:
            await response.aclose()
