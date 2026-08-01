"""FastAPI Web 应用入口与生命周期管理模块

负责 FastAPI 应用创建、CORS 跨域中间件配置、数据库版本校验与根管理员预置，
以及注册系统、鉴权、对话、知识库与模型发现等路由。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, knowledge, model, system
from app.db.migrations import assert_database_at_head
from app.db.redis import close_redis
from app.knowledge_repository import close_knowledge_database
from app.state_repository import seed_root_admin


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期钩子：启动时校验 DB 并初始化管理员，退出时释放 Redis 与数据库连接池"""
    await assert_database_at_head()
    await seed_root_admin()
    try:
        yield
    finally:
        await close_redis()
        await close_knowledge_database()


def create_app() -> FastAPI:
    """创建并初始化 FastAPI 应用工厂实例

    Returns:
        FastAPI: 已配置中间件和路由的应用实例
    """
    application = FastAPI(
        title="智能 RAG 系统（MySQL + Milvus 开发版）",
        version="0.4.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        system.router,
        auth.router,
        chat.router,
        knowledge.router,
        model.router,
    ):
        application.include_router(router)
    return application


# FastAPI 全局应用实例
app = create_app()
