from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import tiktoken
from docx import Document as DocxDocument
from pypdf import PdfReader
from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility


SUPPORTED_EXTENSIONS = {".docx", ".xlsx", ".xls", ".csv", ".txt", ".md", ".pdf"}
DASHSCOPE_DIMENSIONS = [64, 128, 256, 512, 768, 1024, 1536, 2048]


class KnowledgeProcessingError(RuntimeError):
    pass


class EmbeddingServiceError(KnowledgeProcessingError):
    pass


def embedding_config() -> dict[str, Any]:
    model = os.getenv("EMBEDDING_MODEL", "").strip()
    api_base = os.getenv("OPENAI_API_BASE", "").strip()
    dimensions = DASHSCOPE_DIMENSIONS if "dashscope" in api_base.lower() else [256, 512, 768, 1024, 1536, 3072]
    return {
        "model": model,
        "provider": "DashScope" if "dashscope" in api_base.lower() else "OpenAI Compatible",
        "supported_dimensions": dimensions,
        "default_dimension": 1024 if "dashscope" in api_base.lower() else 1536,
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
    }


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise KnowledgeProcessingError("文本编码无法识别，请转换为 UTF-8 后重试")


def _stringify_cell(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _extract_excel(content: bytes) -> str:
    try:
        workbook = pd.ExcelFile(io.BytesIO(content))
    except Exception as exc:
        raise KnowledgeProcessingError(f"Excel 文件无法读取: {exc}") from exc

    sections: list[str] = []
    for sheet_name in workbook.sheet_names:
        frame = workbook.parse(sheet_name=sheet_name, dtype=object)
        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        if frame.empty:
            continue
        columns = [str(column).strip() or f"列{index + 1}" for index, column in enumerate(frame.columns)]
        rows = [f"[工作表: {sheet_name}]", "字段: " + " | ".join(columns)]
        for row_number, values in enumerate(frame.itertuples(index=False, name=None), start=2):
            parts = [
                f"{column}: {_stringify_cell(value)}"
                for column, value in zip(columns, values)
                if _stringify_cell(value)
            ]
            if parts:
                rows.append(f"第{row_number}行 | " + " | ".join(parts))
        if len(rows) > 2:
            sections.append("\n".join(rows))
    if not sections:
        raise KnowledgeProcessingError("Excel 文件中没有可处理的数据")
    return "\n\n".join(sections)


def extract_document(file_name: str, content: bytes) -> tuple[str, str]:
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        if suffix == ".doc":
            raise KnowledgeProcessingError("暂不支持旧版 .doc，请另存为 .docx 后上传")
        raise KnowledgeProcessingError(f"不支持 {suffix or '无扩展名'} 文件")

    if suffix in {".txt", ".md", ".csv"}:
        text = _decode_text(content)
    elif suffix in {".xlsx", ".xls"}:
        text = _extract_excel(content)
    elif suffix == ".docx":
        try:
            document = DocxDocument(io.BytesIO(content))
            blocks = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
            for table_index, table in enumerate(document.tables, start=1):
                blocks.append(f"[表格 {table_index}]")
                blocks.extend(
                    " | ".join(cell.text.strip() for cell in row.cells)
                    for row in table.rows
                    if any(cell.text.strip() for cell in row.cells)
                )
            text = "\n".join(blocks)
        except Exception as exc:
            raise KnowledgeProcessingError(f"DOCX 文件无法读取: {exc}") from exc
    else:
        try:
            reader = PdfReader(io.BytesIO(content))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise KnowledgeProcessingError(f"PDF 文件无法读取: {exc}") from exc

    text = text.replace("\x00", "").strip()
    if not text:
        raise KnowledgeProcessingError("文件中没有提取到可处理文本")
    return text, suffix.removeprefix(".")


def split_text_by_tokens(text: str, chunk_tokens: int, overlap_tokens: int) -> list[dict[str, Any]]:
    if not 64 <= chunk_tokens <= 8192:
        raise KnowledgeProcessingError("切片 Token 数必须在 64 到 8192 之间")
    if overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
        raise KnowledgeProcessingError("Overlap 必须大于等于 0 且小于切片 Token 数")

    encoding = tiktoken.get_encoding("cl100k_base")
    token_ids = encoding.encode(text)
    if not token_ids:
        raise KnowledgeProcessingError("文件没有可切片的 Token")

    chunks: list[dict[str, Any]] = []
    step = chunk_tokens - overlap_tokens
    for start in range(0, len(token_ids), step):
        current_ids = token_ids[start : start + chunk_tokens]
        chunk_text = encoding.decode(current_ids).strip()
        if chunk_text:
            chunks.append({"text": chunk_text, "token_count": len(current_ids)})
        if start + chunk_tokens >= len(token_ids):
            break
    return chunks


def connect_milvus() -> None:
    connections.connect(
        alias="default",
        host=os.getenv("MILVUS_HOST", "localhost"),
        port=os.getenv("MILVUS_PORT", "19530"),
    )


def create_collection(collection_name: str, vector_dimension: int) -> None:
    connect_milvus()
    if utility.has_collection(collection_name):
        return
    schema = CollectionSchema(
        fields=[
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="document_name", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="source_type", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="token_count", dtype=DataType.INT64),
            FieldSchema(name="uploaded_by", dtype=DataType.INT64),
            FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=vector_dimension),
        ],
        description=f"RAG 知识库，向量维度 {vector_dimension}",
    )
    collection = Collection(collection_name, schema=schema)
    collection.create_index(
        field_name="embedding",
        index_params={"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 128}},
    )


def drop_collection(collection_name: str) -> None:
    connect_milvus()
    if utility.has_collection(collection_name):
        utility.drop_collection(collection_name)


async def embed_texts(texts: list[str], vector_dimension: int) -> list[list[float]]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("DASHSCOPE_API_KEY", "").strip()
    api_base = os.getenv("OPENAI_API_BASE", "").strip().rstrip("/")
    model = os.getenv("EMBEDDING_MODEL", "").strip()
    if not api_key or not api_base or not model:
        raise EmbeddingServiceError("后端 .env 缺少 Embedding API Key、URL 或模型配置")

    vectors: list[list[float]] = []
    timeout = httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for start in range(0, len(texts), 10):
            batch = texts[start : start + 10]
            response = await client.post(
                f"{api_base}/embeddings",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "input": batch, "dimensions": vector_dimension, "encoding_format": "float"},
            )
            if response.status_code >= 400:
                try:
                    payload = response.json()
                    detail = payload.get("error", {}).get("message") or str(payload)
                except ValueError:
                    detail = response.text
                raise EmbeddingServiceError(
                    f"向量模型返回 {response.status_code}: {detail[:500]}"
                )
            payload = response.json()
            data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
            batch_vectors = [item.get("embedding") for item in data]
            if len(batch_vectors) != len(batch) or any(not isinstance(vector, list) for vector in batch_vectors):
                raise EmbeddingServiceError("向量模型返回的数据数量或格式不正确")
            for vector in batch_vectors:
                if len(vector) != vector_dimension:
                    raise EmbeddingServiceError(
                        f"向量模型实际返回 {len(vector)} 维，与知识库设定的 {vector_dimension} 维不一致"
                    )
            vectors.extend(batch_vectors)
    return vectors


def insert_chunks(
    collection_name: str,
    chunks: list[dict[str, Any]],
    vectors: list[list[float]],
    document_name: str,
    source_type: str,
    uploaded_by: int,
) -> list[int]:
    connect_milvus()
    collection = Collection(collection_name)
    timestamp = datetime.now(timezone.utc).isoformat()
    result = collection.insert(
        [
            [chunk["text"] for chunk in chunks],
            [document_name for _ in chunks],
            [source_type for _ in chunks],
            list(range(len(chunks))),
            [chunk["token_count"] for chunk in chunks],
            [uploaded_by for _ in chunks],
            [timestamp for _ in chunks],
            vectors,
        ]
    )
    collection.flush()
    return list(result.primary_keys)


def delete_chunks(collection_name: str, primary_keys: list[int]) -> None:
    if not primary_keys:
        return
    connect_milvus()
    collection = Collection(collection_name)
    ids = ", ".join(str(int(primary_key)) for primary_key in primary_keys)
    collection.delete(f"id in [{ids}]")
    collection.flush()


def _live_entity_count(collection: Collection) -> int:
    collection.load()
    result = collection.query(expr="", output_fields=["count(*)"])
    return int(result[0]["count(*)"]) if result else 0


def collection_details(collection_name: str) -> dict[str, Any]:
    connect_milvus()
    if not utility.has_collection(collection_name):
        raise KnowledgeProcessingError("Milvus 集合不存在")
    collection = Collection(collection_name)
    fields = []
    for field in collection.schema.fields:
        params = dict(field.params)
        fields.append(
            {
                "name": field.name,
                "type": field.dtype.name,
                "is_primary": field.is_primary,
                "auto_id": field.auto_id,
                "dimension": params.get("dim"),
                "max_length": params.get("max_length"),
            }
        )
    return {
        "collection_name": collection_name,
        "description": collection.schema.description,
        "entity_count": _live_entity_count(collection),
        "fields": fields,
        "indexes": [index.to_dict() for index in collection.indexes],
    }


def list_chunks(collection_name: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    connect_milvus()
    if not utility.has_collection(collection_name):
        raise KnowledgeProcessingError("Milvus 集合不存在")
    collection = Collection(collection_name)
    collection.load()
    total = _live_entity_count(collection)
    rows = collection.query(
        expr="id >= 0",
        output_fields=[
            "id",
            "text",
            "document_name",
            "source_type",
            "chunk_index",
            "token_count",
            "uploaded_by",
            "created_at",
        ],
        offset=max(0, offset),
        limit=max(1, min(limit, 200)),
    )
    rows.sort(key=lambda row: row.get("id", 0))
    return {"items": rows, "offset": offset, "limit": limit, "total": total}
