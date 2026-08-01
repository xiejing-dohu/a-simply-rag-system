"""向量库 Outbox 异步事务调配 Worker 模块

通过 MySQL Transactional Outbox 模式监听、调配与执行 Milvus Collection 的异步创建、删除与版本一致性检查，
保障 Redis 异常宕机时向量数据的最终一致性。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select

from app.db.mysql import async_session_maker
from app.knowledge_runtime import collection_exists, create_collection, drop_collection
from app.models.document_task import DocumentTask
from app.models.knowledge_base import KnowledgeBase
from app.models.vector_operation import VectorOperation

# 出队轮询间隔（秒）与超时阻断阈值（5分钟）
POLL_INTERVAL_SECONDS = 1.0
PROCESSING_TIMEOUT = timedelta(minutes=5)


def utcnow() -> datetime:
    """获取无时区 UTC 时间"""
    return datetime.now(UTC).replace(tzinfo=None)


async def _claim_operation() -> str | None:
    """抢占并锁定一条待处理 (pending/retry) 或僵死的 Outbox 异步任务记录"""
    now = utcnow()
    stale_before = now - PROCESSING_TIMEOUT
    async with async_session_maker() as session:
        result = await session.execute(
            select(VectorOperation)
            .where(
                or_(
                    and_(
                        VectorOperation.status.in_(["pending", "retry"]),
                        or_(
                            VectorOperation.next_attempt_at.is_(None),
                            VectorOperation.next_attempt_at <= now,
                        ),
                    ),
                    and_(
                        VectorOperation.status == "processing",
                        VectorOperation.updated_at <= stale_before,
                    ),
                )
            )
            .order_by(VectorOperation.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        operation = result.scalar_one_or_none()
        if operation is None:
            return None
        operation.status = "processing"
        operation.attempts += 1
        operation.next_attempt_at = None
        operation.last_error = None
        await session.commit()
        return operation.id


async def _load_operation(operation_id: str) -> dict | None:
    """加载正在处理中的 Outbox 任务数据字典"""
    async with async_session_maker() as session:
        operation = await session.get(VectorOperation, operation_id)
        if operation is None or operation.status != "processing":
            return None
        return {
            "id": operation.id,
            "operation_type": operation.operation_type,
            "resource_id": operation.resource_id,
            "collection_name": operation.collection_name,
            "payload": dict(operation.payload or {}),
        }


async def _has_unfinished_create(resource_id: int, current_id: str) -> bool:
    """检查知识库是否有未完成的集合创建任务"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(VectorOperation.id).where(
                VectorOperation.resource_id == resource_id,
                VectorOperation.operation_type == "create_collection",
                VectorOperation.id != current_id,
                VectorOperation.status.in_(["pending", "retry", "processing"]),
            )
        )
        return result.first() is not None


async def _has_unfinished_document_task(resource_id: int) -> bool:
    """检查知识库是否有排队或运行中的文档上传/切片任务"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(DocumentTask.id).where(
                DocumentTask.knowledge_base_id == resource_id,
                DocumentTask.status.in_(["queued", "processing"]),
            )
        )
        return result.first() is not None


async def _complete(operation_id: str) -> None:
    """将 Outbox 任务标记为 completed，并同步更新 MySQL 知识库主表状态（如 active 或物理删除）"""
    async with async_session_maker() as session:
        operation = await session.get(
            VectorOperation, operation_id, with_for_update=True
        )
        if operation is None:
            return
        knowledge_base = await session.get(
            KnowledgeBase, operation.resource_id, with_for_update=True
        )
        if operation.operation_type == "create_collection":
            if knowledge_base is not None and knowledge_base.status == "creating":
                knowledge_base.status = "active"
        elif operation.operation_type == "drop_collection":
            if knowledge_base is not None:
                await session.delete(knowledge_base)
        operation.status = "completed"
        operation.completed_at = utcnow()
        operation.last_error = None
        await session.commit()


async def _retry(operation_id: str, exc: Exception) -> None:
    """Outbox 任务失败后的指数退避重试逻辑及最大次数超限标记"""
    async with async_session_maker() as session:
        operation = await session.get(
            VectorOperation, operation_id, with_for_update=True
        )
        if operation is None:
            return
        operation.last_error = (str(exc) or exc.__class__.__name__)[:4000]
        if operation.attempts >= operation.max_attempts:
            operation.status = "failed"
            knowledge_base = await session.get(
                KnowledgeBase, operation.resource_id, with_for_update=True
            )
            if knowledge_base is not None:
                knowledge_base.status = (
                    "create_failed"
                    if operation.operation_type == "create_collection"
                    else "delete_failed"
                )
        else:
            operation.status = "retry"
            delay = min(300, 2 ** min(operation.attempts, 8))
            operation.next_attempt_at = utcnow() + timedelta(seconds=delay)
        await session.commit()


async def process_operation(operation_id: str) -> None:
    """执行单个 Outbox 操作（创建/删除 Milvus Collection）"""
    payload = await _load_operation(operation_id)
    if payload is None:
        return
    try:
        if payload["operation_type"] == "create_collection":
            await asyncio.to_thread(
                create_collection,
                payload["collection_name"],
                int(payload["payload"]["vector_dimension"]),
            )
        elif payload["operation_type"] == "drop_collection":
            if await _has_unfinished_create(payload["resource_id"], operation_id):
                raise RuntimeError("等待知识库集合创建任务结束后再删除")
            if await _has_unfinished_document_task(payload["resource_id"]):
                raise RuntimeError("等待正在处理的文档任务结束后再删除知识库")
            await asyncio.to_thread(drop_collection, payload["collection_name"])
        else:
            raise ValueError(f"不支持的向量操作: {payload['operation_type']}")
        await _complete(operation_id)
    except Exception as exc:
        await _retry(operation_id, exc)


async def vector_outbox_worker(stop_event: asyncio.Event) -> None:
    """Outbox 定时轮询主循环 Worker

    同时每隔 60 秒触发一次向量存储一致性对账。
    """
    last_reconciliation = 0.0
    loop = asyncio.get_running_loop()
    while not stop_event.is_set():
        try:
            if loop.time() - last_reconciliation >= 60:
                await reconcile_vector_state()
                last_reconciliation = loop.time()
            operation_id = await _claim_operation()
            if operation_id is None:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue
            await process_operation(operation_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def reconcile_vector_state() -> None:
    """向量数据状态一致性对账逻辑

    检测 MySQL 标记为 active 的知识库，若在 Milvus 中 Collection 缺失，
    将其标记为 inconsistent 状态提示管理员修复。
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(KnowledgeBase.id, KnowledgeBase.collection_name).where(
                KnowledgeBase.status == "active"
            )
        )
        active_items = list(result.all())
    for resource_id, collection_name in active_items:
        exists = await asyncio.to_thread(collection_exists, collection_name)
        if exists:
            continue
        async with async_session_maker() as session:
            item = await session.get(
                KnowledgeBase, resource_id, with_for_update=True
            )
            if item is not None and item.status == "active":
                item.status = "inconsistent"
                await session.commit()
