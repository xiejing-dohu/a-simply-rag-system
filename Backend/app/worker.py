"""后台 Worker 独立启动入口模块

包含并发文档解析/向量化 Worker 与向量存储 Outbox 事务 Worker，
支持 SIGINT/SIGTERM 优雅终止信号捕获及资源清理。
"""

from __future__ import annotations

import asyncio
import signal

from app.core.config import settings
from app.db.migrations import assert_database_at_head
from app.db.mysql import engine
from app.db.redis import close_redis
from app.document_tasks import document_worker
from app.vector_outbox import vector_outbox_worker


async def run_workers() -> None:
    """启动并发 Worker 协程并监听优雅退出信号"""
    # 检查数据库迁移版本
    await assert_database_at_head()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(*_: object) -> None:
        """收到终止信号时设置停止标志位"""
        loop.call_soon_threadsafe(stop_event.set)

    for signal_name in ("SIGINT", "SIGTERM"):
        worker_signal = getattr(signal, signal_name, None)
        if worker_signal is not None:
            signal.signal(worker_signal, request_stop)

    concurrency = max(1, settings.DOCUMENT_WORKER_CONCURRENCY)
    tasks = [
        *[
            asyncio.create_task(
                document_worker(stop_event), name=f"document-worker-{index + 1}"
            )
            for index in range(concurrency)
        ],
        asyncio.create_task(vector_outbox_worker(stop_event), name="vector-outbox"),
    ]
    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_redis()
        await engine.dispose()


def main() -> None:
    """Worker 脚本程序命令行入口"""
    asyncio.run(run_workers())


if __name__ == "__main__":
    main()
