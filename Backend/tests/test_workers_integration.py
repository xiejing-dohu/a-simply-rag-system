"""后台 Worker 与向量处理 Saga 事务集成测试模块

包含文档处理异步任务流程测试、Worker 取消自动重入队测试、Milvus 向量分块确定性 ID 测试及 Outbox 事务 Saga 恢复测试。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select

import app.document_tasks as document_tasks
import app.knowledge_runtime as knowledge_runtime
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
from app.knowledge_runtime import stable_chunk_id


def test_stable_chunk_id_is_deterministic_and_chunk_specific():
    """测试切片主键确定性算法"""
    document_id = str(uuid.uuid4())
    assert stable_chunk_id(document_id, 0) == stable_chunk_id(document_id, 0)
    assert stable_chunk_id(document_id, 0) != stable_chunk_id(document_id, 1)
    assert 0 < stable_chunk_id(document_id, 0) < 2**63


def test_insert_chunks_retries_with_the_same_primary_keys(monkeypatch):
    """测试切片写入 Milvus 时的幂等重试行为"""
    class FakeCollection:
        def __init__(self):
            self.batches = []
            self.flushes = 0

        def upsert(self, rows):
            self.batches.append(rows)

        def flush(self):
            self.flushes += 1

    collection = FakeCollection()
    monkeypatch.setattr(knowledge_runtime, "connect_milvus", lambda: None)
    monkeypatch.setattr(
        knowledge_runtime, "require_idempotent_collection", lambda _name: None
    )
    monkeypatch.setattr(
        knowledge_runtime, "Collection", lambda _name: collection
    )
    chunks = [
        {"text": "first", "token_count": 1},
        {"text": "second", "token_count": 1},
    ]
    vectors = [[0.0] * 2, [1.0] * 2]
    document_id = str(uuid.uuid4())

    first = knowledge_runtime.insert_chunks(
        "test", chunks, vectors, "a.txt", "text", 1, document_id
    )
    second = knowledge_runtime.insert_chunks(
        "test", chunks, vectors, "a.txt", "text", 1, document_id
    )

    assert first == second
    assert [row["id"] for row in collection.batches[0]] == first
    assert [row["id"] for row in collection.batches[1]] == first
    assert all(
        row["document_id"] == document_id
        for batch in collection.batches
        for row in batch
    )
    assert collection.flushes == 2


@pytest.mark.asyncio
async def test_document_task_is_claimed_and_persisted(
    monkeypatch, tmp_path
):
    """测试文档解析与向量化任务全流程持久化处理"""
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
        "require_idempotent_collection",
        lambda _name: None,
    )
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
            assert document.ingestion_id == task_id
            assert document.chunk_count == 1
    finally:
        async with async_session_maker() as session:
            kb = await session.get(KnowledgeBase, kb_id)
            if kb is not None:
                await session.delete(kb)
                await session.commit()


@pytest.mark.asyncio
async def test_cancelled_worker_requeues_task_and_keeps_upload(monkeypatch, tmp_path):
    """测试 Worker 强制终止/取消时，任务安全释放并返回 queued 状态"""
    task_id = str(uuid.uuid4())
    upload = tmp_path / f"{task_id}.upload"
    upload.write_text("cancel me", encoding="utf-8")
    entered_embedding = asyncio.Event()
    async with async_session_maker() as session:
        kb = KnowledgeBase(
            name="cancel-test",
            description="",
            collection_name=f"kb_cancel_{uuid.uuid4().hex}",
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
        document_tasks, "require_idempotent_collection", lambda _name: None
    )
    monkeypatch.setattr(
        document_tasks,
        "extract_document",
        lambda _name, _content: ("cancel me", "text"),
    )
    monkeypatch.setattr(
        document_tasks,
        "split_text_by_tokens",
        lambda *_args: [{"text": "cancel me", "token_count": 2}],
    )

    async def waiting_embed(_texts, _dimension):
        entered_embedding.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(document_tasks, "embed_texts", waiting_embed)

    try:
        await create_task(
            task_id=task_id,
            knowledge_base_id=kb_id,
            created_by=1,
            file_name="cancel.txt",
            content_type="text/plain",
            file_size=upload.stat().st_size,
            temp_path=str(upload),
            chunk_tokens=128,
            overlap_tokens=16,
        )
        assert await claim_task(task_id) == task_id
        running = asyncio.create_task(process_task(task_id))
        await asyncio.wait_for(entered_embedding.wait(), timeout=2)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

        assert upload.exists()
        async with async_session_maker() as session:
            task = await session.get(DocumentTask, task_id)
            assert task is not None
            assert task.status == "queued"
            assert task.stage == "queued"
            assert task.heartbeat_at is None
    finally:
        upload.unlink(missing_ok=True)
        async with async_session_maker() as session:
            kb = await session.get(KnowledgeBase, kb_id)
            if kb is not None:
                await session.delete(kb)
                await session.commit()


@pytest.mark.asyncio
async def test_vector_outbox_create_and_delete_saga(monkeypatch):
    """测试 Vector Outbox 创建与删除集合的异步 Saga 事务调配"""
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
