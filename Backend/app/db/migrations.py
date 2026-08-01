"""数据库 Alembic 迁移校验模块

在系统启动时检查 MySQL 数据库的当前版本与 Alembic 脚本的版本是否一致。
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.db.mysql import engine

# Backend 项目根目录路径
BACKEND_ROOT = Path(__file__).resolve().parents[2]


async def assert_database_at_head() -> None:
    """校验当前数据库 Schema 是否已升级至最新 Alembic Head 版本

    若数据库版本与 alembic 脚本最新版本不一致，则抛出 RuntimeError 阻止应用启动。

    Raises:
        RuntimeError: 当数据库未升级或迁移版本不匹配时抛出。
    """
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())

    async with engine.connect() as connection:
        current_heads = set(
            await connection.run_sync(
                lambda sync_connection: MigrationContext.configure(
                    sync_connection
                ).get_current_heads()
            )
        )

    if current_heads != expected_heads:
        raise RuntimeError(
            "数据库迁移版本不匹配："
            f"current={sorted(current_heads)}, expected={sorted(expected_heads)}。"
            "请先在 Backend 目录执行 `uv run alembic upgrade head`。"
        )
