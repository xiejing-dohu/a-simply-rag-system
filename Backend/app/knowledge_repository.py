"""知识库与文档数据仓库模块

封装 SQLAlchemy 数据库操作，包含知识库元数据 CRUD、文档元数据插入、
向量异步 Outbox 事务记录生成（如创建/删除 Collection）及幂等控制。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.mysql import async_session_maker, engine
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument
from app.models.vector_operation import VectorOperation


async def close_knowledge_database() -> None:
    """清理并释放 MySQL 数据库引擎连接池"""
    await engine.dispose()


def serialize_knowledge_base(item: KnowledgeBase) -> dict[str, Any]:
    """将 KnowledgeBase ORM 对象序列化为字典字典

    Args:
        item (KnowledgeBase): ORM 实体

    Returns:
        dict[str, Any]: 结构化 JSON 字典
    """
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "collection_name": item.collection_name,
        "embedding_model": item.embedding_model,
        "vector_dimension": item.vector_dimension,
        "file_count": item.file_count,
        "chunk_count": item.chunk_count,
        "status": item.status,
        "generation": item.generation,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat(),
    }


def serialize_document(item: KnowledgeDocument) -> dict[str, Any]:
    """将 KnowledgeDocument ORM 对象序列化为字典字典

    Args:
        item (KnowledgeDocument): ORM 实体

    Returns:
        dict[str, Any]: 结构化 JSON 字典
    """
    return {
        "id": item.id,
        "name": item.name,
        "size": item.size,
        "content_type": item.content_type,
        "source_type": item.source_type,
        "chunk_tokens": item.chunk_tokens,
        "overlap_tokens": item.overlap_tokens,
        "chunk_count": item.chunk_count,
        "total_tokens": item.total_tokens,
        "vector_dimension": item.vector_dimension,
        "embedding_model": item.embedding_model,
        "created_at": item.created_at.isoformat(),
    }


async def list_knowledge_bases() -> list[KnowledgeBase]:
    """按创建时间倒序查询所有知识库列表

    Returns:
        list[KnowledgeBase]: 知识库实体列表
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
        )
        return list(result.scalars().all())


async def get_knowledge_base(knowledge_base_id: int) -> KnowledgeBase | None:
    """获取指定 ID 且状态为 active 的有效知识库

    Args:
        knowledge_base_id (int): 知识库 ID

    Returns:
        KnowledgeBase | None: 存在返回实体，否则返回 None
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.status == "active",
            )
        )
        return result.scalar_one_or_none()


async def get_knowledge_base_any_status(
    knowledge_base_id: int,
) -> KnowledgeBase | None:
    """查询任意状态（包括 creating/deleting）的知识库记录"""
    async with async_session_maker() as session:
        return await session.get(KnowledgeBase, knowledge_base_id)


async def create_knowledge_base_record(
    *,
    name: str,
    description: str,
    collection_name: str,
    embedding_model: str,
    vector_dimension: int,
    created_by: int,
) -> KnowledgeBase:
    """原子化创建知识库记录并写入创建 Collection 的 Outbox 事务记录

    Returns:
        KnowledgeBase: 新建的知识库实体
    """
    async with async_session_maker() as session:
        item = KnowledgeBase(
            name=name,
            description=description,
            collection_name=collection_name,
            embedding_model=embedding_model,
            vector_dimension=vector_dimension,
            created_by=created_by,
            status="creating",
        )
        session.add(item)
        await session.flush()
        # 写入 VectorOperation 事务收件箱
        session.add(
            VectorOperation(
                id=str(uuid.uuid4()),
                idempotency_key=f"knowledge_base:create:{item.id}:{item.generation}",
                operation_type="create_collection",
                resource_type="knowledge_base",
                resource_id=item.id,
                collection_name=item.collection_name,
                payload={"vector_dimension": item.vector_dimension},
            )
        )
        await session.commit()
        await session.refresh(item)
        return item


async def request_knowledge_base_deletion(
    knowledge_base_id: int,
) -> VectorOperation | None:
    """原子化标记知识库状态为 deleting，并向 Outbox 插入删除 Milvus Collection 的异步操作记录

    Args:
        knowledge_base_id (int): 知识库 ID

    Returns:
        VectorOperation | None: 向量 Outbox 任务实体，知识库不存在则返回 None
    """
    async with async_session_maker() as session:
        item = await session.get(
            KnowledgeBase, knowledge_base_id, with_for_update=True
        )
        if item is None:
            return None
        key = f"knowledge_base:delete:{item.id}:{item.generation}"
        existing = await session.execute(
            select(VectorOperation).where(VectorOperation.idempotency_key == key)
        )
        operation = existing.scalar_one_or_none()
        if operation is None:
            operation = VectorOperation(
                id=str(uuid.uuid4()),
                idempotency_key=key,
                operation_type="drop_collection",
                resource_type="knowledge_base",
                resource_id=item.id,
                collection_name=item.collection_name,
                payload={"generation": item.generation},
            )
            session.add(operation)
        elif operation.status == "failed":
            operation.status = "retry"
            operation.attempts = 0
            operation.next_attempt_at = None
            operation.last_error = None
        item.status = "deleting"
        # 取消未完成的创建操作
        pending_create = await session.execute(
            select(VectorOperation).where(
                VectorOperation.resource_type == "knowledge_base",
                VectorOperation.resource_id == item.id,
                VectorOperation.operation_type == "create_collection",
                VectorOperation.status.in_(["pending", "retry"]),
            )
        )
        for create_operation in pending_create.scalars():
            create_operation.status = "cancelled"
            create_operation.completed_at = create_operation.updated_at
        await session.commit()
        await session.refresh(operation)
        return operation


async def get_vector_operation(operation_id: str) -> VectorOperation | None:
    """根据 ID 查询指定向量 Outbox 操作"""
    async with async_session_maker() as session:
        return await session.get(VectorOperation, operation_id)


def serialize_vector_operation(item: VectorOperation) -> dict[str, Any]:
    """序列化 VectorOperation ORM 实例为字典"""
    return {
        "id": item.id,
        "operation_type": item.operation_type,
        "resource_id": item.resource_id,
        "status": item.status,
        "attempts": item.attempts,
        "max_attempts": item.max_attempts,
        "error": item.last_error,
        "created_at": item.created_at.isoformat(),
        "completed_at": (
            item.completed_at.isoformat() if item.completed_at else None
        ),
    }


async def list_documents(knowledge_base_id: int) -> list[KnowledgeDocument]:
    """获取指定知识库下所有文档记录

    Args:
        knowledge_base_id (int): 知识库 ID

    Returns:
        list[KnowledgeDocument]: 文档实体列表
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
            .order_by(KnowledgeDocument.created_at.desc())
        )
        return list(result.scalars().all())


async def add_document_record(
    *,
    ingestion_id: str,
    knowledge_base_id: int,
    name: str,
    size: int,
    content_type: str | None,
    source_type: str,
    chunk_tokens: int,
    overlap_tokens: int,
    chunk_count: int,
    total_tokens: int,
    vector_dimension: int,
    embedding_model: str,
) -> KnowledgeDocument:
    """幂等写入导入完成的文档元数据，并原子累加知识库的文档数与切片数

    Args:
        ingestion_id (str): 导入任务的唯一标识 ID
        knowledge_base_id (int): 所属知识库 ID
        ...

    Returns:
        KnowledgeDocument: 已持久化的文档记录
    """
    async with async_session_maker() as session:
        existing = await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.ingestion_id == ingestion_id
            )
        )
        existing_item = existing.scalar_one_or_none()
        if existing_item is not None:
            return existing_item
        item = KnowledgeDocument(
            ingestion_id=ingestion_id,
            knowledge_base_id=knowledge_base_id,
            name=name,
            size=size,
            content_type=content_type,
            source_type=source_type,
            chunk_tokens=chunk_tokens,
            overlap_tokens=overlap_tokens,
            chunk_count=chunk_count,
            total_tokens=total_tokens,
            vector_dimension=vector_dimension,
            embedding_model=embedding_model,
        )
        session.add(item)
        knowledge_base = await session.get(
            KnowledgeBase, knowledge_base_id, with_for_update=True
        )
        if knowledge_base is None:
            raise LookupError("知识库不存在")
        knowledge_base.file_count += 1
        knowledge_base.chunk_count += chunk_count
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            duplicate = await session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.ingestion_id == ingestion_id
                )
            )
            duplicate_item = duplicate.scalar_one_or_none()
            if duplicate_item is None:
                raise
            return duplicate_item
        await session.refresh(item)
        return item
