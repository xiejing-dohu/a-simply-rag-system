from app.db.mysql import engine, Base
from app.models.user import User
from app.core.security import hash_password
from app.db.mysql import async_session_maker
from sqlalchemy import select
# 需要导入所有模型，以确保在Base.metadata.create_all时它们已被注册
import app.models

async def init_database():
    """创建所有 MySQL 表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
async def create_admin_user():
    """创建默认管理员 (admin/admin123)"""
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        user = result.scalar_one_or_none()
        if not user:
            admin_user = User(
                username="admin",
                email="admin@admin.com",
                hashed_password=hash_password("admin123"),
                role="admin"
            )
            session.add(admin_user)
            await session.commit()
