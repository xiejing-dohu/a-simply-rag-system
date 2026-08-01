"""API 路由统一导出模块"""

from app.api import auth, chat, dependencies, knowledge, model, system

__all__ = ["auth", "chat", "dependencies", "knowledge", "model", "system"]
