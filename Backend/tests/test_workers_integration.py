from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

import app.document_tasks as document_tasks
import app.vector_outbox as vector_outbox
from app.db.mysql import async_session_maker
from app.document_tasks import claim_task, create_task, process_task
from app.knowledge_repository import (
    create_knowledge_base_record,
    request_knowledge_base_deletion,
)
from app.models.document_task import DocumentTask
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument
from app.models.vector_operation import VectorOperation


@pytest.mark.asyncio
async def test_document_task_is_claimed_and_persisted(
    monkeypatch, tmp_path
):
    task_id = str(uuid.uuid4())
    collection_name = f"kb_worker_test_{uuid.uuid4().hex}"
    upload = tmp_path / f"{task_id}.upload"
    upload.write_text("integration content", encoding="utf-8")
    async with async_session_maker() as session:
        kb = KnowledgeBase(
            name="worker-test",
            description="",
            collection_name=collection_name,
            embedding_model="test-embedding",
            vector_dimension=64,
            created_by=1,
            status="active",
        )
        session.add(kb)
        await session.commit()
        await session.refresh(kb)
        kb_id = kb.id

    monkeypatch.setattr(
        document_tasks,
        "extract_document",
        lambda _name, _content: ("integration content", "text"),
    )
    monkeypatch.setattr(
        document_tasks,
        "split_text_by_tokens",
        lambda _text, _chunk, _overlap: [
            {"text": "integration content", "token_count": 2}
        ],
    )

    async def fake_embed(_texts, _dimension):
        return [[0.0] * 64]

    monkeypatch.setattr(document_tasks, "embed_texts", fake_embed)
    monkeypatch.setattr(
        document_tasks,
        "insert_chunks",
        lambda *_args, **_kwargs: [900001],
    )
    monkeypatch.setattr(
        document_tasks,
        "delete_chunks",
        lambda *_args, **_kwargs: None,
    )

    try:
        await create_task(
            task_id=task_id,
            knowledge_base_id=kb_id,
            created_by=1,
            file_name="integration.txt",
            content_type="text/plain",
            file_size=upload.stat().st_size,
            temp_path=str(upload),
            chunk_tokens=128,
            overlap_tokens=16,
        )
        assert await claim_task(task_id) == task_id
        assert await claim_task(task_id) is None
        await process_task(task_id)

        async with async_session_maker() as session:
            task = await session.get(DocumentTask, task_id)
            assert task is not None
            assert task.status == "completed"
            assert task.attempts == 1
            assert task.result_document_id is not None
            document = await session.get(
                KnowledgeDocument, task.result_document_id
            )
            assert document is not None
            assert document.chunk_count == 1
    finally:
        async with async_session_maker() as session:
            kb = await session.get(KnowledgeBase, kb_id)
            if kb is not None:
                await session.delete(kb)
                await session.commit()


@pytest.mark.asyncio
async def test_vector_outbox_create_and_delete_saga(monkeypatch):
    collection_name = f"kb_outbox_e2e_{uuid.uuid4().hex}"
    created_collections: set[str] = set()

    def fake_create(name: str, _dimension: int) -> None:
        created_collections.add(name)

    def fake_drop(name: str) -> None:
        created_collections.discard(name)

    monkeypatch.setattr(vector_outbox, "create_collection", fake_create)
    monkeypatch.setattr(vector_outbox, "drop_collection", fake_drop)
    kb = await create_knowledge_base_record(
        name="outbox-e2e",
        description="",
        collection_name=collection_name,
        embedding_model="test",
        vector_dimension=64,
        created_by=1,
    )
    operation_ids: list[str] = []
    try:
        create_operation_id = await vector_outbox._claim_operation()
        assert create_operation_id is not None
        operation_ids.append(create_operation_id)
        await vector_outbox.process_operation(create_operation_id)
        async with async_session_maker() as session:
            active = await session.get(KnowledgeBase, kb.id)
            assert active is not None and active.status == "active"
        assert collection_name in created_collections

        delete_operation = await request_knowledge_base_deletion(kb.id)
        assert delete_operation is not None
        claimed_delete = await vector_outbox._claim_operation()
        assert claimed_delete == delete_operation.id
        operation_ids.append(claimed_delete)
        await vector_outbox.process_operation(claimed_delete)
        async with async_session_maker() as session:
            assert await session.get(KnowledgeBase, kb.id) is None
            completed = await session.get(VectorOperation, claimed_delete)
            assert completed is not None and completed.status == "completed"
        assert collection_name not in created_collections
    finally:
        async with async_session_maker() as session:
            leftover = await session.get(KnowledgeBase, kb.id)
            if leftover is not None:
                await session.delete(leftover)
            await session.execute(
                delete(VectorOperation).where(
                    VectorOperation.resource_id == kb.id
                )
            )
            await session.commit()
