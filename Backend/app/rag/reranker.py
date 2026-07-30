from __future__ import annotations

from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings


class RerankServiceError(RuntimeError):
    pass


class TransientRerankError(RuntimeError):
    pass


async def rerank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    provider = settings.RERANK_PROVIDER.strip().lower()
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
