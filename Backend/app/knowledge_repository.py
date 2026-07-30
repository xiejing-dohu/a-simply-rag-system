from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.db.mysql import async_session_maker, engine
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument
from app.models.vector_operation import VectorOperation


async def close_knowledge_database() -> None:
    await engine.dispose()


def serialize_knowledge_base(item: KnowledgeBase) -> dict[str, Any]:
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
    async with async_session_maker() as session:
        result = await session.execute(
            select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
        )
        return list(result.scalars().all())


async def get_knowledge_base(knowledge_base_id: int) -> KnowledgeBase | None:
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
    """Atomically mark a KB unavailable and append its Milvus drop operation."""

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
    async with async_session_maker() as session:
        return await session.get(VectorOperation, operation_id)


def serialize_vector_operation(item: VectorOperation) -> dict[str, Any]:
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
    async with async_session_maker() as session:
        result = await session.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
            .order_by(KnowledgeDocument.created_at.desc())
        )
        return list(result.scalars().all())


async def add_document_record(
    *,
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
    async with async_session_maker() as session:
        item = KnowledgeDocument(
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
        await session.commit()
        await session.refresh(item)
        return item
