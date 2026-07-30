import uuid
import os
import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import UploadFile
from app.models.knowledge_base import KnowledgeBase
from app.db.milvus import create_knowledge_collection, delete_collection, get_milvus_connection
from app.rag.document_loader import load_document, split_documents
from app.rag.embeddings import get_embedding_model

async def create_knowledge_base(db: AsyncSession, name: str, description: str, user_id: int) -> KnowledgeBase:
    collection_name = f"kb_{uuid.uuid4().hex}"
    
    # 在 Milvus 中创建集合
    create_knowledge_collection(collection_name)
    
    kb = KnowledgeBase(
        name=name,
        description=description,
        collection_name=collection_name,
        created_by=user_id
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb

async def get_knowledge_bases(db: AsyncSession) -> list[KnowledgeBase]:
    result = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
    return list(result.scalars().all())

async def get_knowledge_base(db: AsyncSession, kb_id: int) -> KnowledgeBase | None:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    return result.scalar_one_or_none()

async def delete_knowledge_base(db: AsyncSession, kb_id: int) -> bool:
    kb = await get_knowledge_base(db, kb_id)
    if not kb:
        return False
        
    delete_collection(kb.collection_name)
    
    await db.delete(kb)
    await db.commit()
    return True

async def upload_document(db: AsyncSession, kb_id: int, file: UploadFile) -> dict:
    kb = await get_knowledge_base(db, kb_id)
    if not kb:
        raise ValueError("Knowledge base not found")
        
    # 临时保存文件
    os.makedirs("temp_uploads", exist_ok=True)
    temp_path = f"temp_uploads/{uuid.uuid4().hex}_{file.filename}"
    
    try:
        async with aiofiles.open(temp_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
            
        # 解析文档
        docs = load_document(temp_path)
        chunks = split_documents(docs)
        
        if not chunks:
            return {"status": "error", "message": "No content extracted"}
            
        # 生成 Embeddings 并存入 Milvus
        embeddings_model = get_embedding_model()
        texts = [chunk.page_content for chunk in chunks]
        embeddings = embeddings_model.embed_documents(texts)
        
        get_milvus_connection()
        from pymilvus import Collection
        collection = Collection(kb.collection_name)
        
        entities = [
            texts,
            embeddings
        ]
        collection.insert(entities)
        collection.flush()
        
        # 更新文件数
        kb.file_count += 1
        await db.commit()
        
        return {"status": "success", "chunks_inserted": len(chunks)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
