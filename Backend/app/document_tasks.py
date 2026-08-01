"""文档处理异步任务模块

包含文件上传落盘、任务入队、Worker 抢占与心跳维持、
文档文本解析、Token 切片、生成嵌入向量以及幂等写入 Milvus/MySQL 的核心异步处理流程。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import and_, or_, select

from app.db.mysql import async_session_maker
from app.db.redis import redis_client
from app.knowledge_repository import add_document_record, get_knowledge_base
from app.knowledge_runtime import (
    delete_chunks,
    embed_texts,
    extract_document,
    insert_chunks,
    require_idempotent_collection,
    split_text_by_tokens,
)
from app.models.document_task import DocumentTask

# Redis 队列 Key
QUEUE_KEY = "documents:queue"
# 上传文件临时存储根目录
UPLOAD_ROOT = Path(__file__).resolve().parents[1] / "data" / "uploads"
# 单个文件上传限制大小 (30 MB)
MAX_FILE_SIZE = 30 * 1024 * 1024
# 任务租约超时时间（2分钟未收到心跳判定为僵死）
TASK_LEASE_TIMEOUT = timedelta(minutes=2)
# 心跳刷新间隔（30秒）
HEARTBEAT_INTERVAL_SECONDS = 30


def utcnow() -> datetime:
    """获取无时区 UTC 时间"""
    return datetime.now(UTC).replace(tzinfo=None)


def serialize_task(item: DocumentTask) -> dict[str, Any]:
    """将 DocumentTask 实体序列化为字典对象"""
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
        "attempts": item.attempts,
        "result_document_id": item.result_document_id,
        "error": item.error,
        "created_at": item.created_at.isoformat(),
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
    }


async def save_upload(upload_file, task_id: str) -> tuple[Path, int]:
    """保存前端上传的二进制流到本地临时目录

    Args:
        upload_file: FastAPI / Starlette UploadFile 对象
        task_id (str): 关联的任务 UUID

    Returns:
        tuple[Path, int]: (保存的临时文件路径, 文件字节大小)
    """
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
    """在数据库中创建排队状态的文档处理任务记录"""
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
    """将任务 ID 推入 Redis 唤醒队列"""
    await redis_client.rpush(QUEUE_KEY, task_id)


async def get_task(task_id: str, user_id: int, is_admin: bool) -> DocumentTask | None:
    """查询指定任务（增加权限控制：管理员可看全局，普通员工仅能看本人任务）"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(DocumentTask).where(DocumentTask.id == task_id)
        )
        item = result.scalar_one_or_none()
        if item is None or (not is_admin and item.created_by != user_id):
            return None
        return item


async def _set_task(task_id: str, **changes: Any) -> None:
    """原子化更新任务状态、阶段与进度百分比"""
    async with async_session_maker() as session:
        item = await session.get(DocumentTask, task_id, with_for_update=True)
        if item is None:
            return
        for key, value in changes.items():
            setattr(item, key, value)
        if item.status == "processing":
            item.heartbeat_at = utcnow()
        await session.commit()


async def claim_task(task_id: str | None = None) -> str | None:
    """从数据库抢占一个待处理的任务（包含过期的超时租约任务）"""
    now = utcnow()
    stale_before = now - TASK_LEASE_TIMEOUT
    eligible = or_(
        DocumentTask.status == "queued",
        and_(
            DocumentTask.status == "processing",
            or_(
                DocumentTask.heartbeat_at.is_(None),
                DocumentTask.heartbeat_at <= stale_before,
            ),
        ),
    )
    async with async_session_maker() as session:
        statement = (
            select(DocumentTask)
            .where(eligible)
            .order_by(DocumentTask.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if task_id is not None:
            statement = statement.where(DocumentTask.id == task_id)
        result = await session.execute(statement)
        task = result.scalar_one_or_none()
        if task is None:
            return None
        task.status = "processing"
        task.stage = "parsing"
        task.progress = 10
        task.attempts += 1
        task.heartbeat_at = now
        task.started_at = task.started_at or now
        task.finished_at = None
        task.error = None
        await session.commit()
        return task.id


async def _heartbeat(task_id: str) -> None:
    """任务处理后台续约心跳循环"""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        async with async_session_maker() as session:
            task = await session.get(DocumentTask, task_id)
            if task is None or task.status != "processing":
                return
            task.heartbeat_at = utcnow()
            await session.commit()


async def process_task(task_id: str) -> None:
    """文档处理流水线主函数

    依次执行：文件读取 -> 文本提取 (parsing) -> Token 切片 (splitting)
    -> 向量化生成 (embedding) -> Milvus upsert (milvus) -> 数据库元数据持久化 (metadata)。
    """
    async with async_session_maker() as session:
        task = await session.get(DocumentTask, task_id)
        if task is None or task.status != "processing":
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
    heartbeat = asyncio.create_task(_heartbeat(task_id))
    cleanup_file = False
    try:
        knowledge_base = await get_knowledge_base(payload["knowledge_base_id"])
        if knowledge_base is None:
            raise LookupError("知识库不存在")
        await asyncio.to_thread(
            require_idempotent_collection, knowledge_base.collection_name
        )
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
            task_id,
        )

        await _set_task(task_id, stage="metadata", progress=92)
        try:
            document = await add_document_record(
                ingestion_id=task_id,
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
            finished_at=utcnow(),
            heartbeat_at=None,
        )
        cleanup_file = True
    except asyncio.CancelledError:
        await asyncio.shield(
            _set_task(
                task_id,
                status="queued",
                stage="queued",
                progress=0,
                error="Worker 已停止，任务等待重新处理",
                finished_at=None,
                heartbeat_at=None,
            )
        )
        raise
    except Exception as exc:
        await _set_task(
            task_id,
            status="failed",
            stage="failed",
            error=(str(exc) or exc.__class__.__name__)[:4000],
            finished_at=utcnow(),
            heartbeat_at=None,
        )
        cleanup_file = True
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        if cleanup_file:
            with suppress(OSError):
                path.unlink(missing_ok=True)


async def document_worker(stop_event: asyncio.Event) -> None:
    """文档处理 Worker 轮询逻辑（Redis 作为提速提醒，MySQL 作为可靠持久源）"""
    while not stop_event.is_set():
        hinted_task_id: str | None = None
        try:
            result = await redis_client.blpop(QUEUE_KEY, timeout=1)
            if result:
                hinted_task_id = result[1]
        except asyncio.CancelledError:
            raise
        except RedisError:
            pass
        claimed_task_id = None
        try:
            if hinted_task_id is not None:
                claimed_task_id = await claim_task(hinted_task_id)
            if claimed_task_id is None:
                claimed_task_id = await claim_task()
            if claimed_task_id is not None:
                await process_task(claimed_task_id)
            else:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(1)
