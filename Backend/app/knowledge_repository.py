from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from app.db.mysql import async_session_maker, engine
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument


async def init_knowledge_tables() -> None:
    """Create only the tables owned by the current knowledge-base runtime."""

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: KnowledgeBase.metadata.create_all(
                sync_connection,
                tables=[
                    KnowledgeBase.__table__,
                    KnowledgeDocument.__table__,
                ],
            )
        )


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
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def delete_knowledge_base_record(knowledge_base_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            delete(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
        )
        await session.commit()
        return bool(result.rowcount)


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
