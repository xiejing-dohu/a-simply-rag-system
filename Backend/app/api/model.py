"""模型发现与获取路由模块

对外暴露支持的大语言模型列表接口。
"""

from fastapi import APIRouter

from app.services.model_catalog import discover_models

router = APIRouter(prefix="/models", tags=["模型"])


@router.get("/")
async def get_models(refresh: bool = False):
    """获取可用对话模型列表（可传 refresh=true 强制刷新缓存）"""
    return await discover_models(refresh=refresh)
