from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.core.deps import get_db, get_current_user, require_admin
from app.models.user import User
from app.schemas.knowledge import KBCreate, KBResponse
from app.services import knowledge_service

router = APIRouter()

@router.get("/", response_model=List[KBResponse])
async def get_knowledge_bases(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await knowledge_service.get_knowledge_bases(db)

@router.post("/", response_model=KBResponse)
async def create_knowledge_base(data: KBCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    return await knowledge_service.create_knowledge_base(db, data.name, data.description, current_user.id)

@router.get("/{id}", response_model=KBResponse)
async def get_knowledge_base(id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    kb = await knowledge_service.get_knowledge_base(db, id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb

@router.delete("/{id}")
async def delete_knowledge_base(id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    success = await knowledge_service.delete_knowledge_base(db, id)
    if not success:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return {"status": "success"}

@router.post("/{id}/upload")
async def upload_document(id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    try:
        return await knowledge_service.upload_document(db, id, file)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{id}/documents")
async def get_documents(id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 模拟返回，真实应用应返回文档记录
    return []
