"""MySQL 数据库异步连接模块

使用 SQLAlchemy + aiomysql 创建异步数据库引擎与 Session 工厂。
"""

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

# 构建 MySQL 数据库异步连接 URL
DATABASE_URL = URL.create(
    drivername="mysql+aiomysql",
    username=settings.MYSQL_USER,
    password=settings.MYSQL_PASSWORD,
    host=settings.MYSQL_HOST,
    port=settings.MYSQL_PORT,
    database=settings.MYSQL_DATABASE,
    query={"charset": "utf8mb4"},
)

# 创建 SQLAlchemy 异步引擎
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

# 异步 Session 会话工厂
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ORM 模型基类
Base = declarative_base()
