"""RAG 知识检索与重排序算法核心模块

支持三种检索模式：
1. dense (向量余弦相似度密集检索)
2. semantic (结合 MMR 最大边际相关性算法的多样性向量检索)
3. hybrid (混合检索：融合文本 BM25 词频与 Dense 向量 RRF 倒数排名融合)

检索完成后支持应用 Token 预算裁剪与生成标准 RAG 提示词。
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from typing import Any, Literal

import numpy as np
import tiktoken
from pymilvus import Collection

from app.knowledge_runtime import connect_milvus, embed_texts
from app.rag.reranker import rerank_candidates

# 检索模式类型声明
RetrievalMode = Literal["semantic", "dense", "hybrid"]

# Milvus 检索输出的字段列表
OUTPUT_FIELDS = [
    "id",
    "text",
    "document_name",
    "source_type",
    "chunk_index",
    "token_count",
    "created_at",
]

# tiktoken 编码器（计算上下文 Token 数量）
_encoding = tiktoken.get_encoding("cl100k_base")


def _hit_to_dict(hit: Any) -> dict[str, Any]:
    """将 Milvus Search 返回的 Hit 对象转为字典结构"""
    item = {field: hit.entity.get(field) for field in OUTPUT_FIELDS}
    item["score"] = float(hit.distance)
    item["embedding"] = hit.entity.get("embedding")
    return item


def _dense_candidates(
    collection_name: str,
    query_vector: list[float],
    candidate_limit: int,
) -> list[dict[str, Any]]:
    """从 Milvus 中进行纯向量余弦相似度（Dense Search）检索候选集"""
    connect_milvus()
    collection = Collection(collection_name)
    collection.load()
    result = collection.search(
        data=[query_vector],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 32}},
        limit=candidate_limit,
        output_fields=[*OUTPUT_FIELDS, "embedding"],
    )
    if not result:
        return []
    hits = result[0]
    return [_hit_to_dict(hits[index]) for index in range(len(hits))]


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    """计算两个向量的余弦相似度"""
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else 0.0


def _mmr_rank(
    candidates: list[dict[str, Any]],
    query_vector: list[float],
    limit: int,
    lambda_mult: float = 0.72,
) -> list[dict[str, Any]]:
    """使用 MMR (Maximal Marginal Relevance) 算法实现兼顾相关性与多样性的重排"""
    if not candidates:
        return []
    query = np.asarray(query_vector, dtype=np.float32)
    remaining = list(candidates)
    selected: list[dict[str, Any]] = []
    while remaining and len(selected) < limit:
        best: dict[str, Any] | None = None
        best_mmr = -math.inf
        for candidate in remaining:
            vector = np.asarray(candidate["embedding"], dtype=np.float32)
            relevance = _cosine(query, vector)
            redundancy = max(
                (
                    _cosine(
                        vector,
                        np.asarray(item["embedding"], dtype=np.float32),
                    )
                    for item in selected
                ),
                default=0.0,
            )
            mmr_score = lambda_mult * relevance - (1 - lambda_mult) * redundancy
            if mmr_score > best_mmr:
                best = candidate
                best_mmr = mmr_score
        if best is None:
            break
        best["score"] = best_mmr
        selected.append(best)
        remaining.remove(best)
    return selected


def _lexical_candidates(
    collection_name: str,
    query_text: str,
    pool_limit: int = 2000,
) -> list[dict[str, Any]]:
    """在内存中使用 BM25 词频计算公式对候选切片进行传统文本关键词检索"""
    connect_milvus()
    collection = Collection(collection_name)
    collection.load()
    rows = collection.query(
        expr="id >= 0",
        output_fields=OUTPUT_FIELDS,
        limit=pool_limit,
    )
    if not rows:
        return []

    query_terms = _encoding.encode(query_text.lower())
    if not query_terms:
        return []
    documents = [_encoding.encode(str(row["text"]).lower()) for row in rows]
    document_frequency = Counter(
        term for terms in documents for term in set(terms)
    )
    average_length = sum(len(terms) for terms in documents) / len(documents)
    query_counts = Counter(query_terms)
    total_documents = len(documents)
    k1 = 1.5
    b = 0.75

    ranked: list[dict[str, Any]] = []
    for row, terms in zip(rows, documents):
        term_counts = Counter(terms)
        score = 0.0
        for term, query_weight in query_counts.items():
            frequency = term_counts.get(term, 0)
            if not frequency:
                continue
            doc_frequency = document_frequency[term]
            inverse_frequency = math.log(
                1 + (total_documents - doc_frequency + 0.5) / (doc_frequency + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * len(terms) / max(1.0, average_length)
            )
            score += (
                inverse_frequency
                * frequency
                * (k1 + 1)
                / denominator
                * query_weight
            )
        if score > 0:
            ranked.append({**row, "score": score, "embedding": None})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def _sparse_candidates(
    collection_name: str,
    query_text: str,
    candidate_limit: int,
) -> list[dict[str, Any]] | None:
    """使用 Milvus 自带的 BM25 稀疏向量索引（针对新 Collection），如果是旧结构返回 None"""
    connect_milvus()
    collection = Collection(collection_name)
    if "sparse" not in {field.name for field in collection.schema.fields}:
        return None
    collection.load()
    result = collection.search(
        data=[query_text],
        anns_field="sparse",
        param={"metric_type": "BM25", "params": {}},
        limit=candidate_limit,
        output_fields=OUTPUT_FIELDS,
    )
    if not result:
        return []
    items: list[dict[str, Any]] = []
    for hit in result[0]:
        item = {field: hit.entity.get(field) for field in OUTPUT_FIELDS}
        item["score"] = float(hit.distance)
        item["embedding"] = None
        items.append(item)
    return items


def _hybrid_rank(
    dense: list[dict[str, Any]],
    lexical: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """使用 RRF (Reciprocal Rank Fusion 倒数排名融合) 融合 Dense 与 BM25 结果"""
    by_id: dict[int, dict[str, Any]] = {}
    fused_scores: Counter[int] = Counter()
    rrf_constant = 60
    for ranking in (dense, lexical):
        for rank, item in enumerate(ranking, start=1):
            item_id = int(item["id"])
            by_id.setdefault(item_id, item)
            fused_scores[item_id] += 1 / (rrf_constant + rank)
    ranked_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
    result = []
    for item_id in ranked_ids[:limit]:
        item = by_id[item_id]
        item["score"] = float(fused_scores[item_id])
        result.append(item)
    return result


def _apply_token_budget(
    ranked: list[dict[str, Any]],
    max_tokens: int,
) -> tuple[list[dict[str, Any]], int]:
    """对检索到的切片应用 Token 预算，超过上限部分自动截断"""
    selected: list[dict[str, Any]] = []
    used_tokens = 0
    for item in ranked:
        remaining = max_tokens - used_tokens
        if remaining <= 0:
            break
        token_ids = _encoding.encode(str(item["text"]))
        if len(token_ids) > remaining:
            if remaining < 32:
                break
            item = dict(item)
            item["text"] = _encoding.decode(token_ids[:remaining]).strip()
            item["token_count"] = remaining
            item["truncated"] = True
            selected.append(item)
            used_tokens += remaining
            break
        item = dict(item)
        item["token_count"] = len(token_ids)
        item["truncated"] = False
        selected.append(item)
        used_tokens += len(token_ids)
    for item in selected:
        item.pop("embedding", None)
    return selected, used_tokens


async def retrieve_context(
    *,
    collection_name: str,
    query_text: str,
    vector_dimension: int,
    mode: RetrievalMode,
    max_tokens: int,
    result_limit: int | None = None,
) -> dict[str, Any]:
    """主检索入口：向量化 Query 并根据 mode 进行检索、混合融合与 Rerank 重排序

    Args:
        collection_name (str): Milvus 集合名称
        query_text (str): 检索查询问题
        vector_dimension (int): 向量维度大小
        mode (RetrievalMode): 检索模式 ("dense", "semantic", "hybrid")
        max_tokens (int): 最大 Token 预算 limit
        result_limit (int | None): 返回最大条数

    Returns:
        dict[str, Any]: {"mode": mode, "retrieved_tokens": used_tokens, "sources": selected}
    """
    if result_limit is None:
        result_limit = min(64, max(12, math.ceil(max_tokens / 256)))
    query_vector = (await embed_texts([query_text], vector_dimension))[0]
    candidate_limit = min(128, max(result_limit * 4, 24))
    dense = await asyncio.to_thread(
        _dense_candidates, collection_name, query_vector, candidate_limit
    )

    if mode == "dense":
        ranked = dense
    elif mode == "semantic":
        ranked = _mmr_rank(dense, query_vector, min(candidate_limit, result_limit * 3))
    else:
        lexical = await asyncio.to_thread(
            _sparse_candidates, collection_name, query_text, candidate_limit
        )
        if lexical is None:
            lexical = await asyncio.to_thread(
                _lexical_candidates, collection_name, query_text
            )
        ranked = _hybrid_rank(dense, lexical, candidate_limit)

    ranked = await rerank_candidates(query_text, ranked, result_limit)
    selected, used_tokens = _apply_token_budget(ranked, max_tokens)
    return {
        "mode": mode,
        "retrieved_tokens": used_tokens,
        "sources": selected,
    }


def format_rag_prompt(retrieval: dict[str, Any]) -> str:
    """将 RAG 检索结果拼接为注入 Prompt 的标准结构化字符串

    Args:
        retrieval (dict[str, Any]): 检索得到的 sources 数据

    Returns:
        str: 包含 [资料 N] 格式的 Prompt 指令字符串
    """
    sources = retrieval["sources"]
    if not sources:
        return (
            "知识库中没有检索到可用内容。请明确告诉用户没有找到相关知识库依据，"
            "不要编造知识库中的事实。"
        )
    blocks = []
    for index, source in enumerate(sources, start=1):
        blocks.append(
            f"[资料 {index}] 文件={source['document_name']} "
            f"切片={source['chunk_index']}\n{source['text']}"
        )
    context = "\n\n".join(blocks)
    return (
        "你正在使用 RAG 知识库回答问题。请优先依据下面资料作答；"
        "引用具体事实时使用 [资料 N] 标记。资料不足时明确说明，不要杜撰。\n\n"
        f"{context}"
    )
