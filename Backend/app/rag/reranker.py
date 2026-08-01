"""Rerank 重排序服务模块

对初步检索得到的候选文档切片使用 Cross-Encoder / Reranker 模型（如 DashScope Qwen Rerank）
进行精准相关性打分与重新排序。
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings


class RerankServiceError(RuntimeError):
    """Rerank 服务异常"""
    pass


class TransientRerankError(RuntimeError):
    """Rerank 暂态网络异常"""
    pass


async def rerank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """调用 Rerank 模型重新打分候选文档

    Args:
        query (str): 用户查询问题
        candidates (list[dict[str, Any]]): 粗筛出来的候选文档列表
        limit (int): 截取的最大返回数量

    Returns:
        list[dict[str, Any]]: 按重排序得分由高到低排列的文档列表
    """
    provider = settings.RERANK_PROVIDER.strip().lower()
    # 如果未开启 Rerank 或候选集为空，直接返回前 limit 个结果
    if provider in {"", "none", "disabled"} or not candidates:
        return candidates[:limit]
    if provider != "dashscope":
        raise RerankServiceError(f"不支持的 Rerank 服务商: {provider}")

    api_url = settings.RERANK_API_URL.strip()
    api_key = settings.RERANK_API_KEY.strip() or settings.OPENAI_API_KEY.strip()
    if not api_url or not api_key:
        raise RerankServiceError("已启用 Rerank，但缺少 RERANK_API_URL 或 API Key")

    documents = [str(item["text"]) for item in candidates]
    payload = {
        "model": settings.RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": min(limit, len(documents)),
        "instruct": "Given a question, retrieve passages that answer the question.",
    }
    timeout = httpx.Timeout(connect=15.0, read=90.0, write=30.0, pool=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response: httpx.Response | None = None
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
                retry=retry_if_exception_type(
                    (httpx.TransportError, TransientRerankError)
                ),
                reraise=True,
            ):
                with attempt:
                    response = await client.post(
                        api_url,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise TransientRerankError(
                            f"Rerank 服务暂时不可用: {response.status_code}"
                        )
            assert response is not None
    except (httpx.TransportError, TransientRerankError) as exc:
        raise RerankServiceError(str(exc)) from exc

    if response.status_code >= 400:
        raise RerankServiceError(
            f"Rerank 服务返回 {response.status_code}: {response.text[:500]}"
        )
    try:
        body = response.json()
        results = body.get("results") or body.get("output", {}).get("results") or []
        reranked: list[dict[str, Any]] = []
        for result in results:
            index = int(result["index"])
            if not 0 <= index < len(candidates):
                continue
            item = dict(candidates[index])
            item["retrieval_score"] = item.get("score")
            item["score"] = float(
                result.get("relevance_score", result.get("score", 0.0))
            )
            reranked.append(item)
    except (TypeError, ValueError, KeyError) as exc:
        raise RerankServiceError("Rerank 服务返回格式不正确") from exc
    return reranked[:limit]
