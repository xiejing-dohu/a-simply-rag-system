"""API 接口契约单元测试模块

确保后端路由定义与前端调用接口契约保持兼容，防止接口路径意外改动或路由缺失。
"""

from app.main import app, create_app

# 前端依赖的预设后端 API 路由清单
EXPECTED_ROUTES = {
    "/",
    "/health",
    "/auth/token",
    "/auth/refresh",
    "/auth/logout",
    "/auth/register",
    "/auth/me",
    "/auth/users",
    "/auth/users/{user_id}",
    "/auth/users/{user_id}/token-usage/reset",
    "/chat/conversations",
    "/chat/conversations/{conversation_id}",
    "/chat/conversations/{conversation_id}/messages",
    "/chat/conversations/{conversation_id}/messages/stream",
    "/chat/conversations/{conversation_id}/model",
    "/chat/conversations/{conversation_id}/rag",
    "/knowledge-bases/",
    "/knowledge-bases/embedding-config",
    "/knowledge-bases/operations/{operation_id}",
    "/knowledge-bases/tasks/{task_id}",
    "/knowledge-bases/{knowledge_base_id}",
    "/knowledge-bases/{knowledge_base_id}/documents/",
    "/knowledge-bases/{knowledge_base_id}/milvus/chunks",
    "/knowledge-bases/{knowledge_base_id}/milvus/schema",
    "/models/",
}


def test_frontend_api_routes_are_preserved():
    """测试当前注册的路由包含了全部前端所需的 API 端点"""
    paths = {route.path for route in app.routes}
    assert EXPECTED_ROUTES <= paths


def test_application_factory_creates_isolated_instances():
    """测试应用工厂函数能够独立创建全新实例"""
    assert create_app() is not create_app()
