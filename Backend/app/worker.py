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
    await assert_database_at_head()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(*_: object) -> None:
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
    asyncio.run(run_workers())


if __name__ == "__main__":
    main()
