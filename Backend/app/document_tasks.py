from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import select

from app.db.mysql import async_session_maker
from app.db.redis import redis_client
from app.knowledge_repository import add_document_record, get_knowledge_base
from app.knowledge_runtime import (
    delete_chunks,
    embed_texts,
    extract_document,
    insert_chunks,
    split_text_by_tokens,
)
from app.models.document_task import DocumentTask

QUEUE_KEY = "documents:queue"
UPLOAD_ROOT = Path(__file__).resolve().parents[1] / "data" / "uploads"
MAX_FILE_SIZE = 30 * 1024 * 1024


def serialize_task(item: DocumentTask) -> dict[str, Any]:
    return {
        "id": item.id,
        "knowledge_base_id": item.knowledge_base_id,
        "file_name": item.file_name,
        "file_size": item.file_size,
        "chunk_tokens": item.chunk_tokens,
        "overlap_tokens": item.overlap_tokens,
        "status": item.status,
        "stage": item.stage,
        "progress": item.progress,
        "result_document_id": item.result_document_id,
        "error": item.error,
        "created_at": item.created_at.isoformat(),
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
    }


async def save_upload(upload_file, task_id: str) -> tuple[Path, int]:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_ROOT / f"{task_id}.upload"
    size = 0
    handle = path.open("wb")
    try:
        while chunk := await upload_file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_SIZE:
                raise ValueError("文件不能超过 30 MB")
            await asyncio.to_thread(handle.write, chunk)
    except Exception:
        handle.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        if not handle.closed:
            handle.close()
    if size == 0:
        path.unlink(missing_ok=True)
        raise ValueError("上传文件为空")
    return path, size


async def create_task(
    *,
    task_id: str,
    knowledge_base_id: int,
    created_by: int,
    file_name: str,
    content_type: str | None,
    file_size: int,
    temp_path: str,
    chunk_tokens: int,
    overlap_tokens: int,
) -> DocumentTask:
    async with async_session_maker() as session:
        item = DocumentTask(
            id=task_id,
            knowledge_base_id=knowledge_base_id,
            created_by=created_by,
            file_name=file_name,
            content_type=content_type,
            file_size=file_size,
            temp_path=temp_path,
            chunk_tokens=chunk_tokens,
            overlap_tokens=overlap_tokens,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def enqueue_task(task_id: str) -> None:
    await redis_client.rpush(QUEUE_KEY, task_id)


async def get_task(task_id: str, user_id: int, is_admin: bool) -> DocumentTask | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(DocumentTask).where(DocumentTask.id == task_id)
        )
        item = result.scalar_one_or_none()
        if item is None or (not is_admin and item.created_by != user_id):
            return None
        return item


async def _set_task(task_id: str, **changes: Any) -> None:
    async with async_session_maker() as session:
        item = await session.get(DocumentTask, task_id, with_for_update=True)
        if item is None:
            return
        for key, value in changes.items():
            setattr(item, key, value)
        await session.commit()


async def process_task(task_id: str) -> None:
    async with async_session_maker() as session:
        task = await session.get(DocumentTask, task_id)
        if task is None or task.status == "completed":
            return
        payload = {
            "knowledge_base_id": task.knowledge_base_id,
            "created_by": task.created_by,
            "file_name": task.file_name,
            "content_type": task.content_type,
            "file_size": task.file_size,
            "temp_path": task.temp_path,
            "chunk_tokens": task.chunk_tokens,
            "overlap_tokens": task.overlap_tokens,
        }

    primary_keys: list[int] = []
    path = Path(payload["temp_path"])
    try:
        await _set_task(
            task_id,
            status="processing",
            stage="parsing",
            progress=10,
            started_at=datetime.utcnow(),
            error=None,
        )
        knowledge_base = await get_knowledge_base(payload["knowledge_base_id"])
        if knowledge_base is None:
            raise LookupError("知识库不存在")
        content = await asyncio.to_thread(path.read_bytes)
        text, source_type = await asyncio.to_thread(
            extract_document, payload["file_name"], content
        )

        await _set_task(task_id, stage="splitting", progress=30)
        chunks = await asyncio.to_thread(
            split_text_by_tokens,
            text,
            payload["chunk_tokens"],
            payload["overlap_tokens"],
        )

        await _set_task(task_id, stage="embedding", progress=45)
        vectors = await embed_texts(
            [chunk["text"] for chunk in chunks],
            knowledge_base.vector_dimension,
        )

        await _set_task(task_id, stage="milvus", progress=80)
        primary_keys = await asyncio.to_thread(
            insert_chunks,
            knowledge_base.collection_name,
            chunks,
            vectors,
            payload["file_name"],
            source_type,
            payload["created_by"],
        )

        await _set_task(task_id, stage="metadata", progress=92)
        try:
            document = await add_document_record(
                knowledge_base_id=payload["knowledge_base_id"],
                name=payload["file_name"],
                size=payload["file_size"],
                content_type=payload["content_type"],
                source_type=source_type,
                chunk_tokens=payload["chunk_tokens"],
                overlap_tokens=payload["overlap_tokens"],
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
        await _set_task(
            task_id,
            status="completed",
            stage="completed",
            progress=100,
            result_document_id=document.id,
            finished_at=datetime.utcnow(),
        )
    except Exception as exc:
        await _set_task(
            task_id,
            status="failed",
            stage="failed",
            error=(str(exc) or exc.__class__.__name__)[:4000],
            finished_at=datetime.utcnow(),
        )
    finally:
        with suppress(OSError):
            path.unlink(missing_ok=True)


async def recover_tasks() -> None:
    """Requeue tasks left queued/processing by an interrupted application process."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(DocumentTask.id).where(
                DocumentTask.status.in_(["queued", "processing"])
            )
        )
        for task_id in result.scalars():
            await redis_client.rpush(QUEUE_KEY, task_id)


async def document_worker(stop_event: asyncio.Event) -> None:
    try:
        await recover_tasks()
    except RedisError:
        return
    while not stop_event.is_set():
        try:
            result = await redis_client.blpop(QUEUE_KEY, timeout=2)
            if result:
                await process_task(result[1])
        except asyncio.CancelledError:
            raise
        except RedisError:
            await asyncio.sleep(1)
