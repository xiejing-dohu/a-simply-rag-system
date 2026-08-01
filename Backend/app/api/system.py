"""系统元数据与健康检查路由模块

提供系统根节点响应与存储组件（MySQL, Redis, Milvus）健康状态说明。
"""

from fastapi import APIRouter

router = APIRouter(tags=["系统"])


@router.get("/")
async def root():
    """系统根目录信息提示"""
    return {
        "status": "ok",
        "message": "智能 RAG 系统 MySQL + Milvus 开发版运行中",
        "docs": "/docs",
    }


@router.get("/health")
async def health():
    """系统健康度与存储服务清单响应"""
    return {
        "status": "ok",
        "storage": {
            "users_and_chats": "mysql",
            "login_security": "redis",
            "knowledge_metadata": "mysql",
            "vectors": "milvus",
        },
    }
