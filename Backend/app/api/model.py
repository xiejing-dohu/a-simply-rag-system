from fastapi import APIRouter
from typing import List
from app.schemas.model import ModelListResponse
from app.services.model_service import get_available_models

router = APIRouter()

@router.get("/", response_model=ModelListResponse)
async def get_models():
    models = get_available_models()
    return {"models": models}
