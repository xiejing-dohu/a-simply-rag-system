"""Redis 异步客户端模块

初始化 Redis 连接池，并提供应用关闭时的连接清理句柄。
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import settings

# 异步 Redis 客户端实例（自动对字符串响应解码）
redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)


async def close_redis() -> None:
    """关闭异步 Redis 连接客户端"""
    await redis_client.aclose()
