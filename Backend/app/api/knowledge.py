"""知识库生命周期、文档解析入队及 Milvus 索引调试查看路由模块

包含创建/删除知识库、文档异步上传入队、任务进度查询、文档列表查看以及 Milvus Collection Schema 和向量切片的调试探测接口。
"""

import asyncio
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from redis.exceptions import RedisError

from app.api.dependencies import admin_user, current_user
from app.document_tasks import (
    create_task as create_document_task,
    enqueue_task,
    get_task as get_document_task_record,
    save_upload,
    serialize_task,
)
from app.knowledge_repository import (
    create_knowledge_base_record,
    get_knowledge_base,
    get_vector_operation,
    list_documents,
    list_knowledge_bases,
    request_knowledge_base_deletion,
    serialize_document,
    serialize_knowledge_base,
    serialize_vector_operation,
)
from app.knowledge_runtime import (
    KnowledgeProcessingError,
    collection_details,
    embedding_config,
    list_chunks,
)
from app.schemas.knowledge import KnowledgeBaseCreate

router = APIRouter(prefix="/knowledge-bases", tags=["知识库"])


@router.get("/embedding-config")
async def get_embedding_config(_: Annotated[object, Depends(current_user)]):
    """获取系统 Embedding 模型配置与支持的向量维度列表"""
    return embedding_config()


@router.get("/")
async def get_knowledge_bases(_: Annotated[object, Depends(current_user)]):
    """获取所有知识库元数据列表"""
    return [
        serialize_knowledge_base(item) for item in await list_knowledge_bases()
    ]


@router.post("/", status_code=202)
async def create_knowledge_base(
    data: KnowledgeBaseCreate, user=Depends(admin_user)
):
    """管理员接口：创建新的知识库，触发底层异步创建 Milvus Collection 任务"""
    config = embedding_config()
    if data.vector_dimension not in config["supported_dimensions"]:
        raise HTTPException(
            status_code=422,
            detail=f"当前向量模型支持的维度为: {config['supported_dimensions']}",
        )
    try:
        knowledge_base = await create_knowledge_base_record(
            name=data.name,
            description=data.description or "",
            collection_name=f"kb_{uuid.uuid4().hex}",
            embedding_model=config["model"],
            vector_dimension=data.vector_dimension,
            created_by=user.id,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"创建知识库任务失败: {exc}") from exc
    return serialize_knowledge_base(knowledge_base)


@router.delete("/{knowledge_base_id}", status_code=202)
async def delete_knowledge_base(
    knowledge_base_id: int, _: Annotated[object, Depends(admin_user)]
):
    """管理员接口：软删除标记知识库，并向向量 Outbox 提交异步清理命令"""
    operation = await request_knowledge_base_deletion(knowledge_base_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"status": "accepted", "operation": serialize_vector_operation(operation)}


@router.get("/operations/{operation_id}")
async def get_knowledge_operation(
    operation_id: str, _: Annotated[object, Depends(admin_user)]
):
    """管理员接口：查询指定向量异步 Outbox 操作的当前处理状态"""
    operation = await get_vector_operation(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="向量操作不存在")
    return serialize_vector_operation(operation)


@router.post("/{knowledge_base_id}/documents/", status_code=202)
async def upload_document(
    knowledge_base_id: int,
    file: Annotated[UploadFile, File()],
    chunk_tokens: Annotated[int, Form(ge=64, le=8192)] = 512,
    overlap_tokens: Annotated[int, Form(ge=0, le=4096)] = 64,
    user=Depends(admin_user),
):
    """管理员接口：上传文档并创建后台异步切片与向量化任务"""
    if not await get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    if overlap_tokens >= chunk_tokens:
        raise HTTPException(status_code=422, detail="Overlap 必须小于切片 Token 数")

    task_id = str(uuid.uuid4())
    try:
        temp_path, file_size = await save_upload(file, task_id)
        task = await create_document_task(
            task_id=task_id,
            knowledge_base_id=knowledge_base_id,
            created_by=user.id,
            file_name=file.filename or "未命名文件",
            content_type=file.content_type,
            file_size=file_size,
            temp_path=str(temp_path),
            chunk_tokens=chunk_tokens,
            overlap_tokens=overlap_tokens,
        )
        try:
            await enqueue_task(task.id)
        except RedisError:
            pass  # MySQL 持久保存任务，Redis 仅用于唤醒 Worker
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"创建文档任务失败: {exc}") from exc
    return {"status": "queued", "task": serialize_task(task)}


@router.get("/tasks/{task_id}")
async def get_document_task(task_id: str, user=Depends(current_user)):
    """查询指定文档异步处理任务的进度与状态"""
    task = await get_document_task_record(
        task_id, user.id, is_admin=user.role == "admin"
    )
    if task is None:
        raise HTTPException(status_code=404, detail="文档任务不存在")
    return serialize_task(task)


@router.get("/{knowledge_base_id}/documents/")
async def get_documents(
    knowledge_base_id: int, _: Annotated[object, Depends(current_user)]
):
    """获取知识库下已成功导入的全部文档列表"""
    if not await get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return [
        serialize_document(item) for item in await list_documents(knowledge_base_id)
    ]


@router.get("/{knowledge_base_id}/milvus/schema")
async def get_milvus_schema(
    knowledge_base_id: int, _: Annotated[object, Depends(current_user)]
):
    """调试接口：获取底层 Milvus Collection Schema 与字段/索引定义"""
    knowledge_base = await get_knowledge_base(knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return await asyncio.to_thread(
            collection_details, knowledge_base.collection_name
        )
    except KnowledgeProcessingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"读取 Milvus 字段失败: {exc}") from exc


@router.get("/{knowledge_base_id}/milvus/chunks")
async def get_milvus_chunks(
    knowledge_base_id: int,
    _: Annotated[object, Depends(current_user)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[int | None, Query(ge=0)] = None,
):
    """调试接口：游标/分页方式读取底层 Milvus 中实际存储的切片向量数据"""
    knowledge_base = await get_knowledge_base(knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return await asyncio.to_thread(
            list_chunks, knowledge_base.collection_name, offset, limit, cursor
        )
    except KnowledgeProcessingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"读取 Milvus 切片失败: {exc}") from exc
