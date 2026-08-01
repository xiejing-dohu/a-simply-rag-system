"""pytest 测试框架全局 Fixtures 配置模块

提供用于端到端 API 测试的异步 AsyncClient 依赖。
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def api_client():
    """提供基于 FastAPI app 依赖注入的测试 HTTP 客户端"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
