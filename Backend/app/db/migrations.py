from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.db.mysql import engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]


async def assert_database_at_head() -> None:
    """Fail fast when the application schema has not been migrated."""

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
